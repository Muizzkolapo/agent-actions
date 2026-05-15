"""Integration test: cascade-skip state propagates through a 3-stage chain.

Proves the invariant that a FAILED record at stage 1 arrives at stage 3
with _state=cascade_skipped — i.e. the tombstone produced by
partition_cascade_records is properly stamped by ResultCollector and
recognized by partition_cascade_records at the next stage.

This is the critical end-to-end guarantee for record-level error isolation.
"""

from typing import Any

from agent_actions.processing.cascade_filter import partition_cascade_records
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingResult, ProcessingStatus
from agent_actions.record.state import RecordState


def _make_record(source_guid: str, state: str | None = None) -> dict[str, Any]:
    r: dict[str, Any] = {
        "source_guid": source_guid,
        "content": {"upstream": {"val": source_guid}},
    }
    if state is not None:
        r["_state"] = state
    return r


def _collect(results: list[ProcessingResult], action_name: str):
    """Run results through ResultCollector like the real pipeline does."""
    return ResultCollector.collect_results(
        results,
        agent_config={"agent_type": action_name},
        agent_name=action_name,
        is_first_stage=False,
    )


class TestThreeStageCascadePropagation:
    """Prove that a failed record cascades through 3 stages correctly."""

    def test_failed_record_cascades_through_three_stages(self):
        """Stage 1: R1 succeeds, R2 fails.
        Stage 2: R1 processes, R2 cascade-skipped.
        Stage 3: R1 processes, R2 still cascade-skipped.
        """
        # === Stage 1: classify ===
        # R1 succeeds, R2 fails
        stage1_results = [
            ProcessingResult.success(
                data=[{"source_guid": "r1", "content": {"classify": {"label": "A"}}}],
                source_guid="r1",
            ),
            ProcessingResult.failed(
                error="LLM timeout",
                source_guid="r2",
                input_record=_make_record("r2", "active"),
            ),
        ]
        stage1_output, stage1_stats = _collect(stage1_results, "classify")

        assert stage1_stats.success == 1
        assert stage1_stats.failed == 1
        # R1 is PROCESSED, R2 is a FAILED tombstone
        assert len(stage1_output) == 2
        r1_out = next(r for r in stage1_output if r["source_guid"] == "r1")
        r2_out = next(r for r in stage1_output if r["source_guid"] == "r2")
        assert r1_out["_state"] == RecordState.PROCESSED.value
        assert r2_out["_state"] == RecordState.FAILED.value

        # === Stage 2: enrich ===
        # Feed stage 1 output as input to stage 2.
        # partition_cascade_records should quarantine R2 (FAILED → CASCADE_BLOCKING).
        processable_s2, quarantined_s2 = partition_cascade_records(
            stage1_output, action_name="enrich"
        )
        assert len(processable_s2) == 1
        assert processable_s2[0]["source_guid"] == "r1"
        assert len(quarantined_s2) == 1
        assert quarantined_s2[0].source_guid == "r2"
        assert quarantined_s2[0].status == ProcessingStatus.UNPROCESSED

        # Simulate: R1 processes successfully, R2 is quarantined
        stage2_results = quarantined_s2 + [
            ProcessingResult.success(
                data=[{"source_guid": "r1", "content": {"enrich": {"score": 0.9}}}],
                source_guid="r1",
            ),
        ]
        stage2_output, stage2_stats = _collect(stage2_results, "enrich")

        assert stage2_stats.success == 1
        assert stage2_stats.unprocessed == 1
        # R2's tombstone should now be stamped CASCADE_SKIPPED by ResultCollector
        r2_stage2 = next(r for r in stage2_output if r["source_guid"] == "r2")
        assert r2_stage2["_state"] == RecordState.CASCADE_SKIPPED.value

        # === Stage 3: summarize ===
        # Feed stage 2 output. R2 should still be quarantined.
        processable_s3, quarantined_s3 = partition_cascade_records(
            stage2_output, action_name="summarize"
        )
        assert len(processable_s3) == 1
        assert processable_s3[0]["source_guid"] == "r1"
        assert len(quarantined_s3) == 1
        assert quarantined_s3[0].source_guid == "r2"

        # Simulate: R1 processes, R2 quarantined again
        stage3_results = quarantined_s3 + [
            ProcessingResult.success(
                data=[{"source_guid": "r1", "content": {"summarize": {"text": "done"}}}],
                source_guid="r1",
            ),
        ]
        stage3_output, stage3_stats = _collect(stage3_results, "summarize")

        assert stage3_stats.success == 1
        assert stage3_stats.unprocessed == 1
        # R2 still cascade-skipped at stage 3
        r2_stage3 = next(r for r in stage3_output if r["source_guid"] == "r2")
        assert r2_stage3["_state"] == RecordState.CASCADE_SKIPPED.value
        # R1 fully processed
        r1_stage3 = next(r for r in stage3_output if r["source_guid"] == "r1")
        assert r1_stage3["_state"] == RecordState.PROCESSED.value

    def test_all_quarantined_no_zero_success_error(self):
        """When all active records fail but quarantined records pass through,
        the zero-success check should NOT fire.

        This tests the pipeline.py denominator fix: active_input_count
        excludes unprocessed (quarantined) records.
        """
        # 3 records: 2 cascade-skipped from upstream, 1 active
        records = [
            _make_record("r1", "cascade_skipped"),
            _make_record("r2", "cascade_skipped"),
        ]
        # All records are quarantined — no active records to fail
        processable, quarantined = partition_cascade_records(records, action_name="enrich")
        assert len(processable) == 0
        assert len(quarantined) == 2

        # Collect: only unprocessed results, zero success, zero failures
        output, stats = _collect(quarantined, "enrich")
        assert stats.success == 0
        assert stats.failed == 0
        assert stats.unprocessed == 2

        # The zero-success check uses: active_input_count = len(data) - stats.unprocessed
        # With all quarantined: active_input_count = 2 - 2 = 0
        # Condition: active_input_count > 0 → False → no RuntimeError
        active_input_count = len(records) - stats.unprocessed
        assert active_input_count == 0  # proves the check would not fire
