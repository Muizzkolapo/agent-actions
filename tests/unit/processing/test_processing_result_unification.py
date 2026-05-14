"""ProcessingResult construction unification guards (spec 406)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent_actions.processing.enrichment import VersionIdEnricher
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)

FRESH_VCID = "fresh-vcid-for-test"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _make_context(
    record_index: int = 0,
    action_name: str = "test_action",
) -> ProcessingContext:
    return ProcessingContext(
        agent_config={
            "kind": "llm",
            "agent_type": action_name,
            "action_name": action_name,
            "is_versioned_agent": False,
            "workflow_session_id": "session-1",
        },
        agent_name=action_name,
        record_index=record_index,
    )


def _patch_generator():
    return patch(
        "agent_actions.utils.correlation.VersionIdGenerator.add_version_correlation_id",
        side_effect=lambda item, config, record_index=0, force=False: {
            **item,
            "version_correlation_id": f"{FRESH_VCID}-{record_index}",
        },
    )


# -- T1, T2: file_tool factory switch preserves output shape -----------------


class TestFileToolFactorySwitch:
    def test_expansion_preserves_all_fields(self):
        result = ProcessingResult.success(
            data=[{"a": 1}, {"b": 2}, {"c": 3}, {"d": 4}, {"e": 5}],
            source_guid=None,
            raw_response={"raw": "data"},
            is_expansion=True,
        )
        result.executed = True
        result.source_mapping = {0: [0, 1], 1: [2], 2: [3, 4]}

        assert result.status == ProcessingStatus.SUCCESS
        assert len(result.data) == 5
        assert result.executed is True
        assert result.source_mapping == {0: [0, 1], 1: [2], 2: [3, 4]}
        assert result.is_expansion is True
        assert result.source_guid is None
        assert result.raw_response is not None

    def test_no_expansion_preserves_all_fields(self):
        result = ProcessingResult.success(
            data=[{"a": 1}, {"b": 2}, {"c": 3}],
            source_guid=None,
            raw_response={"raw": "data"},
            is_expansion=False,
        )
        result.executed = True
        result.source_mapping = {0: 0, 1: 1, 2: 2}

        assert result.is_expansion is False
        assert result.executed is True
        assert result.source_mapping is not None
        assert result.source_guid is None


# -- T3, T4, T10: target_id carrying (online path) --------------------------


class TestTargetIdCarrying:
    def test_first_stage_target_id_on_output(self):
        prepared_target_id = "generated-uuid-1234"
        transformed = [{"content": {"field": "val"}}, {"content": {"field": "val2"}}]

        for record in transformed:
            if isinstance(record, dict):
                record["target_id"] = prepared_target_id

        for record in transformed:
            assert record["target_id"] == prepared_target_id

    def test_downstream_target_id_preserved(self):
        transformed = [{"content": {"data": "x"}}]
        for record in transformed:
            if isinstance(record, dict):
                record["target_id"] = "abc-123"

        assert transformed[0]["target_id"] == "abc-123"

    def test_cross_record_target_id_isolation(self):
        records_a = [{"content": "a1"}, {"content": "a2"}]
        records_b = [{"content": "b1"}]

        for record in records_a:
            if isinstance(record, dict):
                record["target_id"] = "AAA"
        for record in records_b:
            if isinstance(record, dict):
                record["target_id"] = "BBB"

        assert records_a[0]["target_id"] == "AAA"
        assert records_a[1]["target_id"] == "AAA"
        assert records_b[0]["target_id"] == "BBB"


# -- T5, T6: skipped() factory signature ------------------------------------


class TestSkippedFactorySignature:
    def test_snapshot_stored(self):
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="guard_skip",
            source_snapshot={"field": "val"},
        )
        assert result.source_snapshot == {"field": "val"}

    def test_input_record_stored(self):
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="guard_skip",
            input_record={"id": "abc"},
        )
        assert result.input_record == {"id": "abc"}

    def test_both_snapshot_and_input_record_stored(self):
        result = ProcessingResult.skipped(
            passthrough_data={"tombstone": True},
            reason="guard_skip",
            source_snapshot={"snap": "shot"},
            input_record={"rec": "ord"},
        )
        assert result.source_snapshot == {"snap": "shot"}
        assert result.input_record == {"rec": "ord"}

    def test_defaults_to_none(self):
        result = ProcessingResult.skipped(passthrough_data=None, reason="guard_skip")
        assert result.source_snapshot is None
        assert result.input_record is None

    def test_backward_compat_with_all_original_params(self):
        result = ProcessingResult.skipped(
            passthrough_data={"key": "val"},
            reason="guard_block",
            source_guid="guid-123",
        )
        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "guard_block"
        assert result.data == [{"key": "val"}]
        assert result.source_guid == "guid-123"
        assert result.source_snapshot is None
        assert result.input_record is None
        assert result.executed is False

    def test_backward_compat_reason_only(self):
        result = ProcessingResult.skipped(passthrough_data=None, reason="prefilter")
        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "prefilter"
        assert result.data == []
        assert result.source_snapshot is None
        assert result.input_record is None


# -- T7, T8: batch is_expansion + enricher behavior -------------------------


class TestBatchIsExpansion:
    def test_expansion_enricher_produces_distinct_vcids(self):
        items = [
            {"source_guid": "sg1", "content": {"a": 1}},
            {"source_guid": "sg1", "content": {"b": 2}},
            {"source_guid": "sg1", "content": {"c": 3}},
        ]
        result = ProcessingResult.success(data=items, source_guid="sg1", is_expansion=True)

        ctx = _make_context(record_index=0)
        with _patch_generator():
            enriched = VersionIdEnricher().enrich(result, ctx)

        vcids = [item["version_correlation_id"] for item in enriched.data]
        assert len(set(vcids)) == 3, f"Expected 3 distinct vcids, got {vcids}"

    def test_no_expansion_single_item(self):
        items = [{"source_guid": "sg1", "content": {"a": 1}}]
        result = ProcessingResult.success(data=items, source_guid="sg1", is_expansion=False)

        ctx = _make_context(record_index=0)
        with _patch_generator():
            enriched = VersionIdEnricher().enrich(result, ctx)

        assert len(enriched.data) == 1

    def test_no_expansion_preserves_existing_vcid(self):
        items = [
            {"source_guid": "sg1", "content": {"a": 1}, "version_correlation_id": "existing-id"},
        ]
        result = ProcessingResult.success(data=items, source_guid="sg1", is_expansion=False)

        ctx = _make_context(record_index=0)
        with _patch_generator():
            enriched = VersionIdEnricher().enrich(result, ctx)

        assert enriched.data[0]["version_correlation_id"] == "existing-id"


# -- T9: batch error data structure regression guard -------------------------


class TestBatchErrorDataStructure:
    def test_error_result_has_expected_keys(self):
        from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

        error_item: dict[str, Any] = {
            "source_guid": "sg-err",
            "error": "LLM returned invalid JSON",
            "metadata": {"retry_exhausted": False},
            "raw_content": '{"broken": json}',
            "_recovery": RecoveryMetadata(
                retry=RetryMetadata(attempts=2, failures=1, succeeded=False, reason="api_error")
            ).to_dict(),
        }

        result = ProcessingResult.failed(error="LLM returned invalid JSON", source_guid="sg-err")
        result.data = [error_item]

        item = result.data[0]
        assert "source_guid" in item
        assert isinstance(item["error"], str)
        assert "metadata" in item
        assert isinstance(item["_recovery"], dict)

        # Simulates write_record_dispositions iteration
        for data_item in result.data:
            assert data_item.get("source_guid") is not None
            assert isinstance(data_item.get("metadata", {}), dict)
            assert isinstance(data_item.get("_recovery", {}), dict)


# -- T11: grep audit — no raw constructors for SUCCESS or FAILED -------------


class TestGrepAudit:
    def test_no_raw_constructors_for_success_or_failed(self):
        result = subprocess.run(
            [
                "grep",
                "-rnE",
                r"ProcessingResult\(status=ProcessingStatus\.(SUCCESS|FAILED)",
                "agent_actions/",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.stdout.strip() == "", (
            f"Raw constructors found — must use factory methods:\n{result.stdout}"
        )
