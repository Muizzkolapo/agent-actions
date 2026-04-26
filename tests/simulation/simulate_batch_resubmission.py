"""Manual simulation: batch resubmission loop fix verification.

This script simulates the multi-run batch lifecycle to confirm that:
1. A completed batch is NOT resubmitted on subsequent runs
2. An in-flight batch is NOT resubmitted
3. A failed/cancelled batch IS resubmitted
4. Force flag overrides the completed guard
5. Guard-filtered batches settle correctly (fewer tasks submitted)
6. Reconciliation merges processed + skipped into consolidated output
7. Dispositions correctly mark guard-skipped records as SKIPPED in the DB

Run:
    python tests/simulation/simulate_batch_resubmission.py
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_actions.llm.batch.core.batch_constants import (
    BatchStatus,
    ContextMetaKeys,
    FilterStatus,
)
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_PASSTHROUGH,
)

# ======================================================================
# Mock storage backend with disposition tracking
# ======================================================================


class MockStorageBackend:
    """In-memory storage backend that tracks dispositions."""

    def __init__(self):
        self._dispositions: dict[tuple[str, str, str], str | None] = {}

    def set_disposition(
        self,
        action_name: str,
        record_id: str,
        disposition: str,
        reason: str | None = None,
        **kwargs,
    ) -> None:
        self._dispositions[(action_name, record_id, disposition)] = reason

    def clear_disposition(
        self,
        action_name: str,
        disposition: str | None = None,
        record_id: str | None = None,
    ) -> int:
        keys_to_delete = [
            k
            for k in self._dispositions
            if k[0] == action_name
            and (disposition is None or k[2] == disposition)
            and (record_id is None or k[1] == record_id)
        ]
        for k in keys_to_delete:
            del self._dispositions[k]
        return len(keys_to_delete)

    def has_disposition(
        self, action_name: str, disposition: str, record_id: str | None = None
    ) -> bool:
        return any(
            k[0] == action_name and k[2] == disposition and (record_id is None or k[1] == record_id)
            for k in self._dispositions
        )

    def get_dispositions_by_type(self, action_name: str, disposition: str) -> list[str]:
        """Return record_ids with the given disposition."""
        return [k[1] for k in self._dispositions if k[0] == action_name and k[2] == disposition]


# ======================================================================
# Context map builder — simulates what BatchTaskPreparator produces
# ======================================================================


def build_context_map(
    total_records: int,
    skipped_ids: set[int],
    filtered_ids: set[int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a context map with INCLUDED, SKIPPED, and FILTERED records.

    Mirrors the output of BatchTaskPreparator._process_single_item().
    """
    filtered_ids = filtered_ids or set()
    context_map: dict[str, dict[str, Any]] = {}

    for i in range(total_records):
        custom_id = f"rec-{i:03d}"
        record: dict[str, Any] = {
            "target_id": custom_id,
            "content": {"text": f"Record {i} content", "category": f"cat-{i % 3}"},
            "source_guid": f"sg-{i:03d}",
        }

        if i in skipped_ids:
            BatchContextMetadata.set_filter_status(record, FilterStatus.SKIPPED)
            record[ContextMetaKeys.FILTER_PHASE] = "unified"
        elif i in filtered_ids:
            BatchContextMetadata.set_filter_status(record, FilterStatus.FILTERED)
            record[ContextMetaKeys.FILTER_PHASE] = "unified"
        else:
            BatchContextMetadata.set_filter_status(record, FilterStatus.INCLUDED)

        context_map[custom_id] = record

    return context_map


# ======================================================================
# Simulation runner — submission guard tests (existing)
# ======================================================================


class SimulationRunner:
    """Simulates multiple workflow runs against a real registry on disk."""

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.output_dir = work_dir / "agent_io" / "target" / "my_action"
        self.batch_dir = self.output_dir / "batch"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.batch_dir / ".batch_registry.json"
        self.run_count = 0
        self.submissions: list[dict[str, Any]] = []

    def _make_service(self, force: bool = False) -> BatchSubmissionService:
        svc = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=lambda out_dir: BatchRegistryManager(
                Path(out_dir) / "batch" / ".batch_registry.json"
            ),
            force_batch=force,
        )
        mock_prepared = MagicMock()
        mock_prepared.tasks = [
            {"target_id": f"r{i}", "content": f"data-{i}", "prompt": "p"} for i in range(10)
        ]
        mock_prepared.context_map = {}
        mock_prepared.task_count = 10
        mock_prepared.stats = MagicMock(total_filtered=0, total_skipped=0)
        svc._task_preparator.prepare_tasks.return_value = mock_prepared

        batch_id = f"batch-{len(self.submissions) + 1:03d}"
        svc._client_resolver.get_for_config.return_value = MagicMock(
            submit_batch=MagicMock(return_value=(batch_id, "submitted"))
        )
        return svc

    def submit_run(self, force: bool = False, label: str = "") -> str:
        self.run_count += 1
        svc = self._make_service(force=force)
        with (
            patch("agent_actions.llm.batch.services.submission.fire_event"),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            result = svc.submit_batch_job(
                agent_config={"model_vendor": "openai"},
                batch_name="my_action",
                data=[{"id": i} for i in range(10)],
                output_directory=str(self.output_dir),
            )
        was_new = svc._task_preparator.prepare_tasks.called
        self.submissions.append(
            {
                "run": self.run_count,
                "label": label,
                "batch_id": result.batch_id,
                "new_submission": was_new,
            }
        )
        return result.batch_id

    def set_registry_status(self, batch_name: str, status: str):
        manager = BatchRegistryManager(self.registry_path)
        entry = manager.get_batch_job(batch_name)
        if entry:
            manager.update_status(entry.batch_id, status)

    def print_registry(self):
        if not self.registry_path.exists():
            print("    Registry: (empty)")
            return
        with open(self.registry_path) as f:
            reg = json.load(f)
        for key, entry in reg.items():
            print(f"    [{key}] batch_id={entry['batch_id']} status={entry['status']}")


# ======================================================================
# Scenarios
# ======================================================================


def run_submission_guard_scenarios(work_dir: Path) -> tuple[int, int]:
    """Scenarios 1-5: submission guard logic."""
    passed = 0
    failed = 0

    def check(condition: bool, pass_msg: str, fail_msg: str) -> None:
        nonlocal passed, failed
        if condition:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    # Scenario 1: Completed batch not resubmitted
    print("\n--- Scenario 1: Completed batch is NOT resubmitted ---")
    sim = SimulationRunner(work_dir / "s1")
    bid1 = sim.submit_run(label="initial")
    sim.set_registry_status("my_action", BatchStatus.COMPLETED)
    bid2 = sim.submit_run(label="after completion")
    check(
        bid2 == bid1 and not sim.submissions[-1]["new_submission"],
        "Completed batch was NOT resubmitted",
        "Completed batch was resubmitted!",
    )
    bid3 = sim.submit_run(label="third run")
    check(
        bid3 == bid1 and not sim.submissions[-1]["new_submission"],
        "Still not resubmitted on 3rd run",
        "Resubmitted on 3rd run!",
    )

    # Scenario 2: In-flight blocks
    print("\n--- Scenario 2: In-flight batch blocks resubmission ---")
    sim2 = SimulationRunner(work_dir / "s2")
    bid1 = sim2.submit_run(label="initial")
    sim2.set_registry_status("my_action", BatchStatus.IN_PROGRESS)
    bid2 = sim2.submit_run(label="while in-flight")
    check(
        bid2 == bid1 and not sim2.submissions[-1]["new_submission"],
        "In-flight batch was NOT resubmitted",
        "In-flight batch was resubmitted!",
    )

    # Scenario 3: Failed allows resubmission
    print("\n--- Scenario 3: Failed batch allows resubmission ---")
    sim3 = SimulationRunner(work_dir / "s3")
    sim3.submit_run(label="initial")
    sim3.set_registry_status("my_action", BatchStatus.FAILED)
    bid2 = sim3.submit_run(label="after failure")
    check(
        sim3.submissions[-1]["new_submission"],
        "Failed batch WAS resubmitted",
        "Failed batch was not resubmitted!",
    )

    # Scenario 4: Force overrides
    print("\n--- Scenario 4: Force flag overrides completed guard ---")
    sim4 = SimulationRunner(work_dir / "s4")
    sim4.submit_run(label="initial")
    sim4.set_registry_status("my_action", BatchStatus.COMPLETED)
    sim4.submit_run(force=True, label="forced resubmit")
    check(
        sim4.submissions[-1]["new_submission"],
        "Force flag overrode completed guard",
        "Force flag did not override completed guard!",
    )

    # Scenario 5: Cancelled allows resubmission
    print("\n--- Scenario 5: Cancelled batch allows resubmission ---")
    sim5 = SimulationRunner(work_dir / "s5")
    sim5.submit_run(label="initial")
    sim5.set_registry_status("my_action", BatchStatus.CANCELLED)
    sim5.submit_run(label="after cancel")
    check(
        sim5.submissions[-1]["new_submission"],
        "Cancelled batch WAS resubmitted",
        "Cancelled batch was not resubmitted!",
    )

    return passed, failed


def run_reconciliation_scenarios() -> tuple[int, int]:
    """Scenarios 6-8: reconciliation, passthrough, and disposition logic."""
    passed = 0
    failed = 0

    def check(condition: bool, pass_msg: str, fail_msg: str) -> None:
        nonlocal passed, failed
        if condition:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    # ------------------------------------------------------------------
    # Scenario 6: Reconciler splits processed vs skipped correctly
    # ------------------------------------------------------------------
    print("\n--- Scenario 6: Reconciler identifies passthrough records ---")
    print("  Setup: 10 records — 7 INCLUDED, 3 SKIPPED (guard)")

    context_map = build_context_map(total_records=10, skipped_ids={2, 5, 8})

    # Simulate batch results for the 7 INCLUDED records only
    included_ids = [
        cid
        for cid, row in context_map.items()
        if BatchContextMetadata.get_filter_status(row) == FilterStatus.INCLUDED
    ]
    assert len(included_ids) == 7, f"Expected 7 included, got {len(included_ids)}"

    reconciler = BatchResultReconciler(context_map)
    for cid in included_ids:
        reconciler.mark_processed(cid)

    result = reconciler.reconcile()

    check(
        len(result.processed_ids) == 7,
        f"7 records marked processed (got {len(result.processed_ids)})",
        f"Expected 7 processed, got {len(result.processed_ids)}",
    )

    check(
        len(result.passthrough_records) == 3,
        f"3 records identified as passthrough (got {len(result.passthrough_records)})",
        f"Expected 3 passthrough, got {len(result.passthrough_records)}",
    )

    passthrough_ids = {cid for cid, _ in result.passthrough_records}
    expected_passthrough = {"rec-002", "rec-005", "rec-008"}
    check(
        passthrough_ids == expected_passthrough,
        f"Passthrough IDs match skipped records: {passthrough_ids}",
        f"Expected {expected_passthrough}, got {passthrough_ids}",
    )

    # Verify all passthrough records have SKIPPED status
    for cid, row in result.passthrough_records:
        status = BatchContextMetadata.get_filter_status(row)
        check(
            status == FilterStatus.SKIPPED,
            f"{cid} has SKIPPED status",
            f"{cid} has {status} status, expected SKIPPED",
        )

    check(
        len(result.missing_ids) == 0,
        "No missing IDs (all included records were processed)",
        f"Unexpected missing IDs: {result.missing_ids}",
    )

    # ------------------------------------------------------------------
    # Scenario 7: FILTERED records excluded from passthrough
    # ------------------------------------------------------------------
    print("\n--- Scenario 7: FILTERED records excluded from passthrough ---")
    print("  Setup: 10 records — 6 INCLUDED, 2 SKIPPED, 2 FILTERED")

    context_map_filtered = build_context_map(
        total_records=10, skipped_ids={3, 7}, filtered_ids={1, 9}
    )

    included_ids_f = [
        cid
        for cid, row in context_map_filtered.items()
        if BatchContextMetadata.get_filter_status(row) == FilterStatus.INCLUDED
    ]
    assert len(included_ids_f) == 6, f"Expected 6 included, got {len(included_ids_f)}"

    reconciler_f = BatchResultReconciler(context_map_filtered)
    for cid in included_ids_f:
        reconciler_f.mark_processed(cid)

    result_f = reconciler_f.reconcile()

    check(
        len(result_f.passthrough_records) == 2,
        f"Only 2 passthrough (SKIPPED only, not FILTERED): {[c for c, _ in result_f.passthrough_records]}",
        f"Expected 2 passthrough, got {len(result_f.passthrough_records)}",
    )

    filtered_in_passthrough = [
        cid
        for cid, row in result_f.passthrough_records
        if BatchContextMetadata.get_filter_status(row) == FilterStatus.FILTERED
    ]
    check(
        len(filtered_in_passthrough) == 0,
        "No FILTERED records in passthrough",
        f"FILTERED records leaked into passthrough: {filtered_in_passthrough}",
    )

    # ------------------------------------------------------------------
    # Scenario 8: Disposition writer marks skipped records correctly
    # ------------------------------------------------------------------
    print("\n--- Scenario 8: Disposition writer marks guard-skipped records ---")
    print("  Setup: 10 output items — 7 processed, 3 guard-skipped with _unprocessed=True")

    from agent_actions.llm.batch.services.processing_recovery import write_record_dispositions

    storage = MockStorageBackend()
    mock_service = MagicMock()
    mock_service._storage_backend = storage

    # Build output items as the result processor would produce them
    output_items: list[dict[str, Any]] = []

    # 7 successfully processed records (no _unprocessed flag)
    for i in range(10):
        if i in {2, 5, 8}:
            continue
        output_items.append(
            {
                "content": {"summary": f"LLM response for record {i}"},
                "source_guid": f"sg-{i:03d}",
                "metadata": {"agent_type": "llm"},
            }
        )

    # 3 guard-skipped passthrough records (with _unprocessed=True)
    for i in [2, 5, 8]:
        output_items.append(
            {
                "content": {"text": f"Record {i} content", "category": f"cat-{i % 3}"},
                "source_guid": f"sg-{i:03d}",
                "metadata": {"reason": "guard_skipped", "agent_type": "tombstone"},
                "_unprocessed": True,
            }
        )

    write_record_dispositions(mock_service, output_items, "my_action")

    # Verify: 3 PASSTHROUGH dispositions (guard-skipped records forward data unchanged)
    passthrough_records = storage.get_dispositions_by_type("my_action", DISPOSITION_PASSTHROUGH)
    check(
        len(passthrough_records) == 3,
        f"3 records have PASSTHROUGH disposition: {passthrough_records}",
        f"Expected 3 PASSTHROUGH, got {len(passthrough_records)}: {passthrough_records}",
    )

    expected_passthrough_guids = {"sg-002", "sg-005", "sg-008"}
    check(
        set(passthrough_records) == expected_passthrough_guids,
        "Correct source_guids are PASSTHROUGH",
        f"Expected {expected_passthrough_guids}, got {set(passthrough_records)}",
    )

    # Verify: no FAILED or FILTERED dispositions
    failed_records = storage.get_dispositions_by_type("my_action", DISPOSITION_FAILED)
    check(
        len(failed_records) == 0,
        "No FAILED dispositions (all processed records succeeded)",
        f"Unexpected FAILED dispositions: {failed_records}",
    )

    filtered_records = storage.get_dispositions_by_type("my_action", DISPOSITION_FILTERED)
    check(
        len(filtered_records) == 0,
        "No FILTERED dispositions (guard-skipped != where-clause filtered)",
        f"Unexpected FILTERED dispositions: {filtered_records}",
    )

    # Verify: reasons are set correctly
    for sg in expected_passthrough_guids:
        reason = storage._dispositions.get(("my_action", sg, DISPOSITION_PASSTHROUGH))
        check(
            reason == "guard_skipped",
            f"{sg} disposition reason is 'guard_skipped'",
            f"{sg} reason is '{reason}', expected 'guard_skipped'",
        )

    # Verify: consolidated output has all 10 records
    check(
        len(output_items) == 10,
        "Consolidated output has all 10 records (7 processed + 3 skipped)",
        f"Expected 10 output items, got {len(output_items)}",
    )

    # Verify: processed records have LLM content, skipped have original
    processed_count = sum(1 for item in output_items if not item.get("_unprocessed"))
    skipped_count = sum(1 for item in output_items if item.get("_unprocessed"))
    check(
        processed_count == 7 and skipped_count == 3,
        f"Output split: {processed_count} processed + {skipped_count} skipped = {len(output_items)} total",
        f"Expected 7+3, got {processed_count}+{skipped_count}",
    )

    return passed, failed


def run_simulation():
    """Run the full simulation."""
    print("=" * 70)
    print("BATCH RESUBMISSION GUARD — FULL PIPELINE SIMULATION")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        p1, f1 = run_submission_guard_scenarios(Path(tmpdir))
        p2, f2 = run_reconciliation_scenarios()

    passed = p1 + p2
    failed = f1 + f2
    total = passed + failed

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed}/{total} passed, {failed}/{total} failed")
    if failed == 0:
        print("ALL SCENARIOS PASSED")
    else:
        print("SOME SCENARIOS FAILED")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_simulation()
    sys.exit(0 if success else 1)
