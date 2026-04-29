"""Tests for VersionIdEnricher — is_expansion flag and passthrough preservation."""

from unittest.mock import patch

from agent_actions.processing.enrichment import VersionIdEnricher
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)


def _make_context(record_index=0):
    return ProcessingContext(
        agent_config={"kind": "llm", "agent_type": "summarize"},
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
        side_effect=lambda item, config, record_index=0: {
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

    def test_negative_record_index_skipped(self):
        data = [{"source_guid": "g1"}]
        result = _make_result(data)
        context = _make_context(record_index=-1)

        with _patch_generator() as mock_gen:
            VersionIdEnricher().enrich(result, context)

        mock_gen.assert_not_called()
