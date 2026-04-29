"""Tests for VersionIdEnricher — is_expansion flag and passthrough preservation."""

from unittest.mock import patch

import pytest

from agent_actions.processing.enrichment import VersionIdEnricher
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)


def _make_context(record_index=0):
    return ProcessingContext(
        agent_config={
            "kind": "llm",
            "agent_type": "summarize",
            "is_versioned_agent": True,
            "version_base_name": "summarize",
            "workflow_session_id": "sess-test",
        },
        agent_name="summarize",
        record_index=record_index,
    )


def _make_result(data, is_expansion=False, status=ProcessingStatus.SUCCESS):
    return ProcessingResult(
        status=status,
        data=data,
        executed=True,
        is_expansion=is_expansion,
    )


FRESH_VCID = "vcid-fresh-999"


def _patch_generator():
    """Patch VersionIdGenerator to return a deterministic ID."""
    return patch(
        "agent_actions.utils.correlation.VersionIdGenerator.add_version_correlation_id",
        side_effect=lambda item, config, *, record_index: {
            **item,
            "version_correlation_id": FRESH_VCID,
        },
    )


class TestVersionIdEnricherPassthrough:
    def test_existing_vcid_preserved_when_not_expansion(self):
        """1:1 passthrough: existing version_correlation_id must survive enrichment."""
        data = [{"source_guid": "g1", "version_correlation_id": "vcid-original"}]
        result = _make_result(data, is_expansion=False)
        context = _make_context()

        with _patch_generator() as mock_gen:
            enriched = VersionIdEnricher().enrich(result, context)

        mock_gen.assert_not_called()
        assert enriched.data[0]["version_correlation_id"] == "vcid-original"

    def test_missing_vcid_assigned_when_not_expansion(self):
        """First-stage record without version_correlation_id gets one assigned."""
        data = [{"source_guid": "g1"}]
        result = _make_result(data, is_expansion=False)
        context = _make_context()

        with _patch_generator():
            enriched = VersionIdEnricher().enrich(result, context)

        assert enriched.data[0]["version_correlation_id"] == FRESH_VCID

    def test_existing_vcid_overwritten_when_expansion(self):
        """1→N expansion: existing version_correlation_id must be replaced with fresh IDs."""
        data = [
            {"source_guid": "g1", "version_correlation_id": "vcid-parent"},
            {"source_guid": "g1", "version_correlation_id": "vcid-parent"},
        ]
        result = _make_result(data, is_expansion=True)
        context = _make_context()

        with _patch_generator() as mock_gen:
            enriched = VersionIdEnricher().enrich(result, context)

        assert mock_gen.call_count == 2
        for item in enriched.data:
            assert item["version_correlation_id"] == FRESH_VCID

    def test_filtered_result_skipped(self):
        data = [{"source_guid": "g1", "version_correlation_id": "vcid-abc"}]
        result = _make_result(data, is_expansion=False, status=ProcessingStatus.FILTERED)
        context = _make_context()

        with _patch_generator() as mock_gen:
            enriched = VersionIdEnricher().enrich(result, context)

        mock_gen.assert_not_called()
        assert enriched.data[0]["version_correlation_id"] == "vcid-abc"

    def test_non_versioned_passthrough_skips_assignment(self):
        """Non-versioned 1:1 without expansion must not call the generator."""
        data = [{"source_guid": "g1"}]
        result = _make_result(data, is_expansion=False)
        context = ProcessingContext(
            agent_config={
                "action_name": "some_tool",
                "workflow_session_id": "sess-123",
                "version_base_name": "some_tool",
            },
            agent_name="some_tool",
            record_index=0,
        )

        with _patch_generator() as mock_gen:
            VersionIdEnricher().enrich(result, context)

        mock_gen.assert_not_called()

    def test_non_versioned_expansion_requires_explicit_base_name(self):
        """1→N expansion assigns distinct IDs when version_base_name is configured."""
        from agent_actions.utils.correlation import VersionIdGenerator

        VersionIdGenerator.clear()
        data = [
            {"source_guid": "g1", "version_correlation_id": "vcid-parent"},
            {"source_guid": "g1", "version_correlation_id": "vcid-parent"},
            {"source_guid": "g1", "version_correlation_id": "vcid-parent"},
        ]
        result = _make_result(data, is_expansion=True)
        context = ProcessingContext(
            agent_config={
                "action_name": "flatten_questions",
                "workflow_session_id": "sess-123",
                "version_base_name": "flatten_questions",
            },
            agent_name="flatten_questions",
            record_index=0,
        )

        enriched = VersionIdEnricher().enrich(result, context)
        ids = [item["version_correlation_id"] for item in enriched.data]
        assert len(set(ids)) == 3
        assert all(vcid != "vcid-parent" for vcid in ids)

    def test_negative_record_index_raises(self):
        data = [{"source_guid": "g1"}]
        result = _make_result(data)
        context = _make_context(record_index=-1)

        with _patch_generator() as mock_gen, pytest.raises(ValueError, match="non-negative"):
            VersionIdEnricher().enrich(result, context)

        mock_gen.assert_not_called()

    def test_expansion_second_result_uses_non_colliding_indices(self):
        """Cumulative context.record_index across results: 3 rows then 2 rows → indices 0–4."""
        from agent_actions.utils.correlation import VersionIdGenerator

        VersionIdGenerator.clear()
        cfg = {
            "action_name": "expand",
            "workflow_session_id": "sess-collide",
            "version_base_name": "expand",
        }
        r3 = _make_result(
            [
                {"source_guid": "g", "version_correlation_id": "parent"},
                {"source_guid": "g", "version_correlation_id": "parent"},
                {"source_guid": "g", "version_correlation_id": "parent"},
            ],
            is_expansion=True,
        )
        r2 = _make_result(
            [
                {"source_guid": "g", "version_correlation_id": "parent"},
                {"source_guid": "g", "version_correlation_id": "parent"},
            ],
            is_expansion=True,
        )
        ctx0 = ProcessingContext(agent_config=cfg, agent_name="expand", record_index=0)
        ctx3 = ProcessingContext(agent_config=cfg, agent_name="expand", record_index=3)
        enricher = VersionIdEnricher()
        out3 = enricher.enrich(r3, ctx0)
        out2 = enricher.enrich(r2, ctx3)
        all_ids = [x["version_correlation_id"] for x in out3.data + out2.data]
        assert len(set(all_ids)) == 5

    def test_expansion_missing_version_base_name_raises(self):
        result = _make_result([{"source_guid": "g"}], is_expansion=True)
        context = ProcessingContext(
            agent_config={"workflow_session_id": "sess-x"},
            agent_name="bad",
            record_index=0,
        )
        with pytest.raises(ValueError, match="version_base_name is required"):
            VersionIdEnricher().enrich(result, context)

    def test_expansion_missing_workflow_session_raises(self):
        result = _make_result([{"source_guid": "g"}], is_expansion=True)
        context = ProcessingContext(
            agent_config={"version_base_name": "vb"},
            agent_name="bad",
            record_index=0,
        )
        with pytest.raises(ValueError, match="workflow_session_id"):
            VersionIdEnricher().enrich(result, context)
