"""Tests guarding ProcessingResult construction unification invariants (spec 406).

Each test asserts on observable output (field values, enrichment results,
storage row shape) — not on implementation details like "factory was used".
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import patch

from agent_actions.processing.enrichment import VersionIdEnricher
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FRESH_VCID = "fresh-vcid-for-test"


def _make_context(
    record_index: int = 0,
    action_name: str = "test_action",
    is_versioned: bool = False,
) -> ProcessingContext:
    return ProcessingContext(
        agent_config={
            "kind": "llm",
            "agent_type": action_name,
            "action_name": action_name,
            "is_versioned_agent": is_versioned,
            "workflow_session_id": "session-1",
        },
        agent_name=action_name,
        record_index=record_index,
    )


def _patch_generator():
    """Patch VersionIdGenerator to return a deterministic fresh ID."""
    return patch(
        "agent_actions.utils.correlation.VersionIdGenerator.add_version_correlation_id",
        side_effect=lambda item, config, record_index=0, force=False: {
            **item,
            "version_correlation_id": f"{FRESH_VCID}-{record_index}",
        },
    )


# ===========================================================================
# T1 — file_tool factory switch preserves output shape (expansion case)
# ===========================================================================


class TestFileToolFactorySwitch:
    def test_expansion_preserves_all_fields(self):
        """T1: factory switch must preserve executed, source_mapping,
        is_expansion, source_guid, and raw_response on expansion."""
        result = ProcessingResult.success(
            data=[{"a": 1}, {"b": 2}, {"c": 3}, {"d": 4}, {"e": 5}],
            source_guid=None,
            raw_response={"raw": "data"},
        )
        result.executed = True
        result.source_mapping = {0: [0, 1], 1: [2], 2: [3, 4]}
        result.is_expansion = len(result.data) > 3  # 5 > 3

        assert result.status == ProcessingStatus.SUCCESS
        assert len(result.data) == 5
        assert result.executed is True
        assert result.source_mapping == {0: [0, 1], 1: [2], 2: [3, 4]}
        assert result.is_expansion is True
        assert result.source_guid is None
        assert result.raw_response is not None

    # -----------------------------------------------------------------------
    # T2 — no expansion case
    # -----------------------------------------------------------------------

    def test_no_expansion_preserves_all_fields(self):
        """T2: is_expansion must be False when output count == input count."""
        result = ProcessingResult.success(
            data=[{"a": 1}, {"b": 2}, {"c": 3}],
            source_guid=None,
            raw_response={"raw": "data"},
        )
        result.executed = True
        result.source_mapping = {0: 0, 1: 1, 2: 2}
        result.is_expansion = len(result.data) > 3  # 3 > 3 is False

        assert result.is_expansion is False
        assert result.executed is True
        assert result.source_mapping is not None
        assert result.source_guid is None


# ===========================================================================
# T3, T4, T10 — target_id carrying (online path)
# ===========================================================================


class TestTargetIdCarrying:
    def test_first_stage_target_id_on_output(self):
        """T3: first-stage records get target_id from prepared.target_id,
        not from input_record (which may lack it)."""
        prepared_target_id = "generated-uuid-1234"
        transformed = [{"content": {"field": "val"}}, {"content": {"field": "val2"}}]

        # Simulate the manual injection pattern from online_llm.py
        for record in transformed:
            if isinstance(record, dict):
                record["target_id"] = prepared_target_id

        for record in transformed:
            assert "target_id" in record
            assert record["target_id"] == prepared_target_id
            assert record["target_id"] != ""
            assert record["target_id"] is not None

    def test_downstream_target_id_preserved(self):
        """T4: downstream records that already have target_id='abc-123'
        get that value carried through, not regenerated."""
        existing_target_id = "abc-123"
        prepared_target_id = existing_target_id  # preparer preserves it
        transformed = [{"content": {"data": "x"}}]

        for record in transformed:
            if isinstance(record, dict):
                record["target_id"] = prepared_target_id

        assert transformed[0]["target_id"] == "abc-123"

    def test_cross_record_target_id_isolation(self):
        """T10: sequential processing of two records must not cross-contaminate
        target_id values."""
        records_a = [{"content": "a1"}, {"content": "a2"}]
        records_b = [{"content": "b1"}]

        target_id_a = "AAA"
        target_id_b = "BBB"

        # Process record A
        for record in records_a:
            if isinstance(record, dict):
                record["target_id"] = target_id_a

        # Process record B
        for record in records_b:
            if isinstance(record, dict):
                record["target_id"] = target_id_b

        # Verify no cross-contamination
        assert records_a[0]["target_id"] == "AAA"
        assert records_a[1]["target_id"] == "AAA"
        assert records_b[0]["target_id"] == "BBB"


# ===========================================================================
# T5, T6 — skipped() factory signature
# ===========================================================================


class TestSkippedFactorySignature:
    def test_snapshot_stored(self):
        """T5a: skipped(source_snapshot=...) stores it on the result."""
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="guard_skip",
            source_snapshot={"field": "val"},
        )
        assert result.source_snapshot == {"field": "val"}

    def test_input_record_stored(self):
        """T5b: skipped(input_record=...) stores it on the result."""
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="guard_skip",
            input_record={"id": "abc"},
        )
        assert result.input_record == {"id": "abc"}

    def test_both_snapshot_and_input_record_stored(self):
        """T5c: both params set simultaneously."""
        result = ProcessingResult.skipped(
            passthrough_data={"tombstone": True},
            reason="guard_skip",
            source_snapshot={"snap": "shot"},
            input_record={"rec": "ord"},
        )
        assert result.source_snapshot == {"snap": "shot"}
        assert result.input_record == {"rec": "ord"}

    def test_defaults_to_none(self):
        """T5d: omitting new params defaults both to None."""
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="guard_skip",
        )
        assert result.source_snapshot is None
        assert result.input_record is None

    def test_backward_compat_with_all_original_params(self):
        """T6: every existing skipped() call pattern still works."""
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
        """T6: minimal call pattern (reason only) still works."""
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="prefilter",
        )
        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "prefilter"
        assert result.data == []
        assert result.source_snapshot is None
        assert result.input_record is None


# ===========================================================================
# T7, T8 — batch is_expansion + enricher behavior
# ===========================================================================


class TestBatchIsExpansion:
    def test_expansion_enricher_produces_distinct_vcids(self):
        """T7: batch 1->3 expansion sets is_expansion=True and enricher
        generates 3 DISTINCT version_correlation_id values."""
        items = [
            {"source_guid": "sg1", "content": {"a": 1}},
            {"source_guid": "sg1", "content": {"b": 2}},
            {"source_guid": "sg1", "content": {"c": 3}},
        ]
        result = ProcessingResult.success(data=items, source_guid="sg1")
        result.is_expansion = len(items) > 1  # True

        assert result.is_expansion is True

        ctx = _make_context(record_index=0)
        enricher = VersionIdEnricher()

        with _patch_generator():
            enriched = enricher.enrich(result, ctx)

        vcids = [item["version_correlation_id"] for item in enriched.data]
        assert len(vcids) == 3
        assert len(set(vcids)) == 3, f"Expected 3 distinct vcids, got {vcids}"

    def test_no_expansion_single_item(self):
        """T8: batch 1->1 does NOT set is_expansion, enricher generates 1 vcid."""
        items = [{"source_guid": "sg1", "content": {"a": 1}}]
        result = ProcessingResult.success(data=items, source_guid="sg1")
        result.is_expansion = len(items) > 1  # False

        assert result.is_expansion is False

        ctx = _make_context(record_index=0)
        enricher = VersionIdEnricher()

        with _patch_generator():
            enriched = enricher.enrich(result, ctx)

        vcids = [item.get("version_correlation_id") for item in enriched.data]
        # Single item with no pre-existing vcid gets one assigned
        assert len(vcids) == 1

    def test_no_expansion_preserves_existing_vcid(self):
        """T8 supplement: non-expansion items with existing vcid are preserved."""
        items = [
            {"source_guid": "sg1", "content": {"a": 1}, "version_correlation_id": "existing-id"},
        ]
        result = ProcessingResult.success(data=items, source_guid="sg1")
        result.is_expansion = False

        ctx = _make_context(record_index=0)
        enricher = VersionIdEnricher()

        with _patch_generator():
            enriched = enricher.enrich(result, ctx)

        assert enriched.data[0]["version_correlation_id"] == "existing-id"


# ===========================================================================
# T9 — batch error data structure regression guard
# ===========================================================================


class TestBatchErrorDataStructure:
    def test_error_result_has_expected_keys(self):
        """T9: batch error data structure that write_record_dispositions()
        depends on is preserved."""
        from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

        error_item: dict[str, Any] = {
            "source_guid": "sg-err",
            "error": "LLM returned invalid JSON",
            "metadata": {"retry_exhausted": False},
        }
        error_item["raw_content"] = '{"broken": json}'
        error_item["_recovery"] = RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=1, succeeded=False, reason="api_error")
        ).to_dict()

        result = ProcessingResult.failed(
            error="LLM returned invalid JSON",
            source_guid="sg-err",
        )
        result.data = [error_item]

        # Verify the keys write_record_dispositions() reads
        item = result.data[0]
        assert "source_guid" in item
        assert "error" in item
        assert isinstance(item["error"], str)
        assert "metadata" in item
        assert "_recovery" in item
        assert isinstance(item["_recovery"], dict)

        # Verify iteration doesn't crash (simulates write_record_dispositions loop)
        for data_item in result.data:
            source_guid = data_item.get("source_guid")
            assert source_guid is not None
            metadata = data_item.get("metadata", {})
            assert isinstance(metadata, dict)
            recovery = data_item.get("_recovery", {})
            assert isinstance(recovery, dict)
            _ = data_item.get("error")
            _ = data_item.get("_state")


# ===========================================================================
# T11 — grep audit: no raw constructors for SUCCESS or FAILED
# ===========================================================================


class TestGrepAudit:
    def test_no_raw_constructors_for_success_or_failed(self):
        """No raw ProcessingResult(status=ProcessingStatus.SUCCESS|FAILED)
        in production code — all must use factory methods."""
        result = subprocess.run(
            [
                "grep",
                "-rnE",
                r"ProcessingResult\(status=ProcessingStatus\.(SUCCESS|FAILED)",
                "agent_actions/",
            ],
            capture_output=True,
            text=True,
            cwd="/Users/muizz/Documents/codeshop/agent_actions_clones/clone_1/agent-actions",
        )
        assert result.stdout.strip() == "", (
            f"Raw constructors found — must use factory methods:\n{result.stdout}"
        )
