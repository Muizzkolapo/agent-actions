"""Tests for FILE-mode tool missing record detection.

When a tool returns fewer records than it received, the missing records
should be detected and tombstoned — not silently lost.
"""

from unittest.mock import patch

from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.record.reasons import TOOL_MISSING_RECORD
from agent_actions.record.tracking import TrackedItem
from agent_actions.utils.udf_management.registry import FileUDFResult


def _make_context(agent_name="my_tool"):
    ctx = ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name=agent_name,
    )
    return ctx


def _make_records(*guids):
    """Build input records with source_guid and minimal content."""
    return [{"source_guid": g, "content": {"prev": {"id": i}}} for i, g in enumerate(guids)]


class TestToolMissingRecordDetection:
    """Missing record detection after tool invocation."""

    def test_all_records_returned_no_tombstones(self):
        """Tool returns all records — no warnings, no tombstones."""
        records = _make_records("r1", "r2", "r3")
        context = _make_context()
        context.source_data = records

        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(
                [
                    TrackedItem({"v": 1}, source_index=0),
                    TrackedItem({"v": 2}, source_index=1),
                    TrackedItem({"v": 3}, source_index=2),
                ],
                True,
            ),
        ):
            results = FileToolStrategy().invoke(records, context)

        # Single success result, no missing tombstones
        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS
        assert len(results[0].data) == 3

    def test_tool_drops_records_produces_tombstones(self):
        """Tool drops 2 of 5 records — 2 unprocessed results with tombstones."""
        records = _make_records("r1", "r2", "r3", "r4", "r5")
        context = _make_context()
        context.source_data = records

        # Tool only returns r1, r3, r5 — drops r2 and r4
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(
                [
                    TrackedItem({"v": 1}, source_index=0),
                    TrackedItem({"v": 3}, source_index=2),
                    TrackedItem({"v": 5}, source_index=4),
                ],
                True,
            ),
        ):
            results = FileToolStrategy().invoke(records, context)

        # 1 success + 2 unprocessed
        assert len(results) == 3
        assert results[0].status == ProcessingStatus.SUCCESS
        assert len(results[0].data) == 3

        missing = [r for r in results if r.status == ProcessingStatus.UNPROCESSED]
        assert len(missing) == 2

        missing_guids = {r.source_guid for r in missing}
        assert missing_guids == {"r2", "r4"}

        for r in missing:
            assert r.skip_reason == TOOL_MISSING_RECORD
            assert r.executed is False
            assert len(r.data) == 1
            assert r.data[0].get("_tombstone") is True

    def test_tool_returns_empty_all_records_tombstoned(self):
        """Tool returns empty for non-empty input — all fail via empty-response path."""
        records = _make_records("r1", "r2")
        context = _make_context()
        context.source_data = records

        # Empty response triggers the is_empty_response branch, not missing detection
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=([], True),
        ):
            results = FileToolStrategy().invoke(records, context)

        # Empty-response path produces FAILED results, not unprocessed
        assert len(results) == 2
        for r in results:
            assert r.status == ProcessingStatus.FAILED

    def test_expansion_tool_no_false_positives(self):
        """Tool with expansion (1→3) — no false tombstones for new output GUIDs."""
        records = _make_records("r1")
        context = _make_context()
        context.source_data = records

        # Tool expands 1 record into 3 — output GUIDs differ from input
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(
                [
                    TrackedItem({"child": 1}, source_index=0),
                    TrackedItem({"child": 2}, source_index=0),
                    TrackedItem({"child": 3}, source_index=0),
                ],
                True,
            ),
        ):
            results = FileToolStrategy().invoke(records, context)

        # Expansion: only the success result, no missing tombstones
        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS
        assert results[0].is_expansion is True

    def test_missing_record_tombstone_has_source_guid(self):
        """Tombstone for missing record carries source_guid for disposition writes."""
        records = _make_records("r1", "r2")
        context = _make_context()
        context.source_data = records

        # Tool only returns r1
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(
                [TrackedItem({"v": 1}, source_index=0)],
                True,
            ),
        ):
            results = FileToolStrategy().invoke(records, context)

        missing = [r for r in results if r.status == ProcessingStatus.UNPROCESSED]
        assert len(missing) == 1
        assert missing[0].source_guid == "r2"
        # Tombstone data also carries the guid
        assert missing[0].data[0].get("source_guid") == "r2"

    def test_missing_record_has_input_record(self):
        """Unprocessed result for missing record carries the original input_record."""
        records = _make_records("r1", "r2")
        context = _make_context()
        context.source_data = records

        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(
                [TrackedItem({"v": 1}, source_index=0)],
                True,
            ),
        ):
            results = FileToolStrategy().invoke(records, context)

        missing = [r for r in results if r.status == ProcessingStatus.UNPROCESSED]
        assert len(missing) == 1
        assert missing[0].input_record == records[1]

    def test_warning_logged_for_missing_records(self, capsys):
        """Missing records produce a warning log for each."""
        records = _make_records("r1", "r2", "r3")
        context = _make_context("dropper_tool")
        context.source_data = records

        # Tool drops r2
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(
                [
                    TrackedItem({"v": 1}, source_index=0),
                    TrackedItem({"v": 3}, source_index=2),
                ],
                True,
            ),
        ):
            FileToolStrategy().invoke(records, context)

        stderr = capsys.readouterr().err
        assert "dropper_tool" in stderr
        assert "r2" in stderr

    def test_high_drop_ratio_logs_many_to_one_guidance(self, capsys):
        """When >50% of records are missing, log guidance about source_index lists."""
        records = _make_records("r1", "r2", "r3", "r4", "r5")
        context = _make_context("batch_tool")
        context.source_data = records

        # Tool returns 1 output for 5 inputs — 80% missing
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(
                [TrackedItem({"v": 1}, source_index=0)],
                True,
            ),
        ):
            FileToolStrategy().invoke(records, context)

        stderr = capsys.readouterr().err
        assert "batch_tool" in stderr
        assert "4 of 5" in stderr
        assert "many-to-one" in stderr
        assert "source_index" in stderr
        # No per-record spam
        assert stderr.count("did not return") == 1

    def test_low_drop_ratio_logs_summary_with_guids(self, capsys):
        """When <=50% of records are missing, log summary with missing GUIDs."""
        records = _make_records("r1", "r2", "r3", "r4")
        context = _make_context("filter_tool")
        context.source_data = records

        # Tool drops r3 — 25% missing
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(
                [
                    TrackedItem({"v": 1}, source_index=0),
                    TrackedItem({"v": 2}, source_index=1),
                    TrackedItem({"v": 4}, source_index=3),
                ],
                True,
            ),
        ):
            FileToolStrategy().invoke(records, context)

        stderr = capsys.readouterr().err
        assert "filter_tool" in stderr
        assert "1 of 4" in stderr
        assert "r3" in stderr
        assert "many-to-one" not in stderr

    def test_synthetic_record_no_false_positives(self):
        """Tool merging N inputs into synthetic output — no false tombstones."""
        records = _make_records("r1", "r2")
        context = _make_context()
        context.source_data = records

        # Tool merges 2 inputs into 1 synthetic record (source_index=None)
        udf_result = FileUDFResult(
            outputs=[{"source_index": None, "data": {"merged": True}}],
        )

        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(udf_result, True),
        ):
            results = FileToolStrategy().invoke(records, context)

        # No false tombstones — synthetic record can't be mapped to input GUIDs
        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS
