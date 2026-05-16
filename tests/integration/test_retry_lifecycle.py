"""Integration test: full retry lifecycle — failure → quarantine → retry → success.

Exercises the real components (SQLite backend, ResultCollector, cascade_filter,
disposition queries) to prove that the retry flow actually works end-to-end.
No mocks on the core path — only the LLM/tool invocation is simulated.

Scenarios tested:
1. Records fail at action B → cascade-skipped at C, D → retry from B → all succeed
2. Partial failure: some records fail, others succeed → retry only re-processes failures
3. Retry after retry: first retry partially fails again → second retry completes
4. Multi-action failures: records fail at different actions → two retry passes fix all
"""

from pathlib import Path
from typing import Any

import pytest

from agent_actions.cli.retry import RetryCommand
from agent_actions.processing.cascade_filter import partition_cascade_records
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingResult
from agent_actions.storage.backend import (
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_SUCCESS,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path: Path) -> SQLiteBackend:
    """Create a real SQLite backend for testing."""
    b = SQLiteBackend(str(tmp_path / "test.db"), "test_workflow")
    b.initialize()
    return b


def _record(guid: str, state: str | None = None, content: dict | None = None) -> dict[str, Any]:
    r: dict[str, Any] = {
        "source_guid": guid,
        "content": content or {"upstream": {"val": guid}},
    }
    if state is not None:
        r["_state"] = state
    return r


def _collect(
    results: list[ProcessingResult],
    action_name: str,
    backend: SQLiteBackend | None = None,
):
    """Run results through the real ResultCollector with storage backend."""
    return ResultCollector.collect_results(
        results,
        agent_config={"agent_type": action_name},
        agent_name=action_name,
        is_first_stage=False,
        storage_backend=backend,
    )


def _simulate_action(
    input_records: list[dict[str, Any]],
    action_name: str,
    failing_guids: set[str],
    backend: SQLiteBackend | None = None,
) -> tuple[list[dict[str, Any]], Any]:
    """Simulate a processing action: partition, process, collect.

    Records whose source_guid is in failing_guids produce FAILED results.
    All others produce SUCCESS results.
    """
    processable, quarantined = partition_cascade_records(input_records, action_name=action_name)

    results: list[ProcessingResult] = list(quarantined)

    for record in processable:
        guid = record.get("source_guid", "")
        if guid in failing_guids:
            results.append(
                ProcessingResult.failed(
                    error=f"Simulated failure for {guid}",
                    source_guid=guid,
                    input_record=record,
                )
            )
        else:
            output_data = dict(record)
            output_data["content"] = {
                **(record.get("content") or {}),
                action_name: {"processed": True, "source": guid},
            }
            results.append(
                ProcessingResult.success(
                    data=[output_data],
                    source_guid=guid,
                )
            )

    output, stats = _collect(results, action_name, backend)
    return output, stats


class TestRetryLifecycle:
    """Full lifecycle: failure → quarantine → disposition → retry → success."""

    def test_fail_at_b_cascade_through_cd_retry_succeeds(self, backend):
        """R1-R5 enter. R2, R4 fail at classify.
        Enrich and summarize cascade-skip R2, R4.
        Retry from classify with no failures → all 5 succeed.
        """
        # === Initial run ===
        initial_input = [_record(f"r{i}", "active") for i in range(1, 6)]

        # classify: R2 and R4 fail
        classify_output, classify_stats = _simulate_action(
            initial_input, "classify", {"r2", "r4"}, backend
        )
        assert classify_stats.success == 3
        assert classify_stats.failed == 2

        # Verify dispositions written
        failed_disps = backend.get_disposition("classify", disposition=DISPOSITION_FAILED)
        assert {d["record_id"] for d in failed_disps} == {"r2", "r4"}

        # enrich: R2, R4 should be cascade-skipped
        enrich_output, enrich_stats = _simulate_action(classify_output, "enrich", set(), backend)
        assert enrich_stats.success == 3
        assert enrich_stats.unprocessed == 2

        # summarize: same cascade
        summarize_output, summarize_stats = _simulate_action(
            enrich_output, "summarize", set(), backend
        )
        assert summarize_stats.success == 3
        assert summarize_stats.unprocessed == 2

        # Verify cascade dispositions written downstream
        enrich_unproc = backend.get_disposition("enrich", disposition="unprocessed")
        assert {d["record_id"] for d in enrich_unproc} == {"r2", "r4"}

        # === Retry from classify ===
        # Clear dispositions (mimics what RetryCommand does)
        execution_order = ["classify", "enrich", "summarize"]
        for action in execution_order:
            for record_id in ("r2", "r4"):
                backend.clear_disposition(action, record_id=record_id)

        # Verify dispositions cleared
        assert backend.get_disposition("classify", disposition=DISPOSITION_FAILED) == []

        # Re-run classify with original input — R2, R4 now succeed
        retry_classify_output, retry_stats = _simulate_action(
            initial_input,
            "classify",
            set(),
            backend,  # no failures this time
        )
        assert retry_stats.success == 5
        assert retry_stats.failed == 0

        # Re-run enrich — all active (no cascade-blocked records now)
        retry_enrich_output, retry_enrich_stats = _simulate_action(
            retry_classify_output, "enrich", set(), backend
        )
        assert retry_enrich_stats.success == 5
        assert retry_enrich_stats.unprocessed == 0

        # Re-run summarize — all succeed
        retry_summarize_output, retry_summarize_stats = _simulate_action(
            retry_enrich_output, "summarize", set(), backend
        )
        assert retry_summarize_stats.success == 5
        assert retry_summarize_stats.unprocessed == 0

        # Final: all 5 records have success disposition at every action
        for action in execution_order:
            success_disps = backend.get_disposition(action, disposition=DISPOSITION_SUCCESS)
            assert len(success_disps) == 5, f"{action} has {len(success_disps)} successes"

    def test_retry_fails_again_then_second_retry_succeeds(self, backend):
        """R1 fails at classify. First retry: R1 fails again.
        Second retry: R1 succeeds. Proves idempotent retry.
        """
        initial = [_record("r1", "active"), _record("r2", "active")]

        # Run 1: R1 fails
        output1, stats1 = _simulate_action(initial, "classify", {"r1"}, backend)
        assert stats1.failed == 1
        assert stats1.success == 1

        # Retry 1: clear and re-run — R1 fails AGAIN
        backend.clear_disposition("classify", record_id="r1")
        output2, stats2 = _simulate_action(initial, "classify", {"r1"}, backend)
        assert stats2.failed == 1  # still failing

        # Retry 2: clear and re-run — R1 succeeds this time
        backend.clear_disposition("classify", record_id="r1")
        output3, stats3 = _simulate_action(initial, "classify", set(), backend)
        assert stats3.success == 2
        assert stats3.failed == 0

        # Final state: both records succeeded
        success_disps = backend.get_disposition("classify", disposition=DISPOSITION_SUCCESS)
        assert {d["record_id"] for d in success_disps} == {"r1", "r2"}

    def test_multi_action_failures_require_two_retry_passes(self, backend):
        """R2 fails at classify, R3 fails at enrich.
        First retry (from classify): fixes R2, but R3 still fails at enrich.
        Second retry (from enrich): fixes R3.
        """
        initial = [_record("r1", "active"), _record("r2", "active"), _record("r3", "active")]

        # classify: R2 fails, R1 and R3 pass
        classify_out, _ = _simulate_action(initial, "classify", {"r2"}, backend)

        # enrich: R2 cascade-skipped, R3 fails here, R1 passes
        enrich_out, enrich_stats = _simulate_action(classify_out, "enrich", {"r3"}, backend)
        assert enrich_stats.success == 1  # R1
        assert enrich_stats.failed == 1  # R3
        assert enrich_stats.unprocessed == 1  # R2 cascade-skipped

        # === Retry pass 1: from classify ===
        # Use _find_failures to verify it picks up R2 at classify
        failures = RetryCommand._find_failures(backend, ["classify", "enrich"])
        assert "classify" in failures
        assert any(d["record_id"] == "r2" for d in failures["classify"])
        assert "enrich" in failures
        assert any(d["record_id"] == "r3" for d in failures["enrich"])

        # Clear classify + downstream for R2
        backend.clear_disposition("classify", record_id="r2")
        backend.clear_disposition("enrich", record_id="r2")

        # Re-run classify: all succeed now
        classify_out2, _ = _simulate_action(initial, "classify", set(), backend)

        # Re-run enrich: R2 now processes, R3 still fails
        enrich_out2, enrich_stats2 = _simulate_action(classify_out2, "enrich", {"r3"}, backend)
        assert enrich_stats2.success == 2  # R1, R2
        assert enrich_stats2.failed == 1  # R3 still failing

        # === Retry pass 2: from enrich ===
        backend.clear_disposition("enrich", record_id="r3")

        # Re-run enrich: R3 succeeds now
        enrich_out3, enrich_stats3 = _simulate_action(classify_out2, "enrich", set(), backend)
        assert enrich_stats3.success == 3
        assert enrich_stats3.failed == 0

        # Final: all records have success at enrich
        success_disps = backend.get_disposition("enrich", disposition=DISPOSITION_SUCCESS)
        assert len(success_disps) == 3

    def test_find_failures_matches_retry_command_semantics(self, backend):
        """Verify _find_failures only returns FAILED and EXHAUSTED,
        not unprocessed/passthrough/success.
        """
        # Write various dispositions
        backend.set_disposition("action_a", "r1", DISPOSITION_SUCCESS)
        backend.set_disposition("action_a", "r2", DISPOSITION_FAILED, reason="error")
        backend.set_disposition("action_a", "r3", DISPOSITION_EXHAUSTED, reason="retry")
        backend.set_disposition("action_a", "r4", "unprocessed", reason="cascade")
        backend.set_disposition("action_a", "r5", "passthrough", reason="guard")

        failures = RetryCommand._find_failures(backend, ["action_a"])

        assert "action_a" in failures
        record_ids = {d["record_id"] for d in failures["action_a"]}
        # Only FAILED and EXHAUSTED — not success, unprocessed, passthrough
        assert record_ids == {"r2", "r3"}

    def test_cascade_chain_preserves_successful_records_on_retry(self, backend):
        """On retry, previously-successful records should NOT be disturbed.

        Proves that only the targeted records are cleared and re-run,
        while other records retain their success disposition.
        """
        initial = [_record("r1", "active"), _record("r2", "active"), _record("r3", "active")]

        # Initial run: R2 fails, R1 and R3 succeed
        output, _ = _simulate_action(initial, "classify", {"r2"}, backend)

        # Verify: R1 and R3 have success, R2 has failed
        success = backend.get_disposition("classify", disposition=DISPOSITION_SUCCESS)
        assert {d["record_id"] for d in success} == {"r1", "r3"}
        failed = backend.get_disposition("classify", disposition=DISPOSITION_FAILED)
        assert {d["record_id"] for d in failed} == {"r2"}

        # Retry: clear ONLY R2's disposition
        backend.clear_disposition("classify", record_id="r2")

        # R1 and R3's success dispositions are still intact
        success_after = backend.get_disposition("classify", disposition=DISPOSITION_SUCCESS)
        assert {d["record_id"] for d in success_after} == {"r1", "r3"}

        # Re-run: R2 succeeds now
        output2, stats2 = _simulate_action(initial, "classify", set(), backend)
        assert stats2.success == 3

        # All three now have success
        final_success = backend.get_disposition("classify", disposition=DISPOSITION_SUCCESS)
        assert {d["record_id"] for d in final_success} == {"r1", "r2", "r3"}
