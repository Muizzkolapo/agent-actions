"""Tests for EnrichmentPipeline and enrichers."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.processing.enrichment import (
    Enricher,
    EnrichmentPipeline,
    LineageEnricher,
    VersionIdEnricher,
    MetadataEnricher,
    PassthroughEnricher,
    RequiredFieldsEnricher,
)
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
)


class TestLineageEnricher:
    """Test LineageEnricher."""

    def test_skips_filtered_results(self):
        """FILTERED status → no lineage added."""
        enricher = LineageEnricher()
        result = ProcessingResult.filtered(source_guid="guid-123")
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        assert enriched.data == []
        assert enriched.node_id is None


class TestMetadataEnricher:
    """Test MetadataEnricher."""

    def test_skips_non_executed_results(self):
        """executed=False → no metadata added."""
        enricher = MetadataEnricher()
        result = ProcessingResult.skipped(passthrough_data={}, reason="guard")
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        # Skipped results should not have metadata added
        assert enriched.executed is False

    @patch("agent_actions.utils.metadata.MetadataExtractor.extract_from_response")
    def test_uses_pre_extracted_metadata_when_present(self, mock_extract):
        """pre_extracted_metadata skips MetadataExtractor, uses dict directly."""
        enricher = MetadataEnricher()
        pre_meta = {"model": "gpt-4-batch", "tokens": 200}
        result = ProcessingResult.success(
            data=[{"item": 1}, {"item": 2}],
            pre_extracted_metadata=pre_meta,
        )
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        # MetadataExtractor should NOT be called
        mock_extract.assert_not_called()
        # Both items should have the pre-extracted metadata
        assert enriched.data[0]["metadata"] == pre_meta
        assert enriched.data[1]["metadata"] == pre_meta

    @patch("agent_actions.utils.metadata.MetadataExtractor.extract_from_response")
    @patch("agent_actions.utils.field_management.FieldManager.add_metadata")
    def test_falls_back_to_extraction_when_no_pre_extracted(self, mock_add, mock_extract):
        """When pre_extracted_metadata is None, falls back to MetadataExtractor."""
        mock_metadata = MagicMock()
        mock_metadata.to_dict.return_value = {"model": "gpt-4"}
        mock_extract.return_value = mock_metadata

        enricher = MetadataEnricher()
        result = ProcessingResult.success(
            data=[{"item": 1}],
            raw_response={"text": "response"},
            # pre_extracted_metadata not set (defaults to None)
        )
        context = ProcessingContext(agent_config={"model": "gpt-4"}, agent_name="test")

        enricher.enrich(result, context)

        # MetadataExtractor SHOULD be called
        mock_extract.assert_called_once_with(
            response={"text": "response"}, agent_config={"model": "gpt-4"}
        )


class TestVersionIdEnricher:
    """Test VersionIdEnricher."""

    def test_skips_filtered_results(self):
        """FILTERED status → no loop ID added."""
        enricher = VersionIdEnricher()
        result = ProcessingResult.filtered()
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        assert enriched.data == []


class TestPassthroughEnricher:
    """Test PassthroughEnricher."""

    def test_skips_empty_passthrough_fields(self):
        """Empty passthrough_fields → no changes."""
        enricher = PassthroughEnricher()
        result = ProcessingResult.success(
            data=[{"content": {"key": "value"}}], passthrough_fields={}
        )
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        assert enriched.data[0]["content"] == {"key": "value"}

    def test_merges_passthrough_into_content_dict(self):
        """passthrough_fields merged into item['content']."""
        enricher = PassthroughEnricher()
        result = ProcessingResult.success(
            data=[{"content": {"key": "value"}}],
            passthrough_fields={"extra": "field"},
        )
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        assert enriched.data[0]["content"]["key"] == "value"
        assert enriched.data[0]["content"]["extra"] == "field"

    def test_handles_flat_item_structure(self):
        """Works when item has no 'content' key."""
        enricher = PassthroughEnricher()
        result = ProcessingResult.success(
            data=[{"key": "value"}], passthrough_fields={"extra": "field"}
        )
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        # When no 'content' key, passthrough merges into item itself
        assert enriched.data[0]["key"] == "value"
        assert enriched.data[0]["extra"] == "field"


class TestRequiredFieldsEnricher:
    """Test RequiredFieldsEnricher."""

    def test_skips_filtered_results(self):
        """FILTERED status → no required fields check."""
        enricher = RequiredFieldsEnricher()
        result = ProcessingResult.filtered()
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        assert enriched.data == []


class TestEnrichmentPipeline:
    """Test EnrichmentPipeline."""

    def test_default_enricher_order(self):
        """Default order: Lineage → Metadata → LoopId → Passthrough → RequiredFields → Recovery."""
        from agent_actions.processing.enrichment import RecoveryEnricher

        pipeline = EnrichmentPipeline()

        assert len(pipeline.enrichers) == 6
        assert isinstance(pipeline.enrichers[0], LineageEnricher)
        assert isinstance(pipeline.enrichers[1], MetadataEnricher)
        assert isinstance(pipeline.enrichers[2], VersionIdEnricher)
        assert isinstance(pipeline.enrichers[3], PassthroughEnricher)
        assert isinstance(pipeline.enrichers[4], RequiredFieldsEnricher)
        assert isinstance(pipeline.enrichers[5], RecoveryEnricher)

    def test_custom_enricher_list(self):
        """Can construct pipeline with custom enricher list."""
        custom_enrichers = [LineageEnricher(), MetadataEnricher()]
        pipeline = EnrichmentPipeline(enrichers=custom_enrichers)

        assert len(pipeline.enrichers) == 2
        assert isinstance(pipeline.enrichers[0], LineageEnricher)
        assert isinstance(pipeline.enrichers[1], MetadataEnricher)

    def test_empty_enricher_list_returns_unchanged(self):
        """Empty enricher list returns result unchanged."""
        pipeline = EnrichmentPipeline(enrichers=[])
        result = ProcessingResult.success(data=[{"key": "value"}])
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = pipeline.enrich(result, context)

        assert enriched.data == [{"key": "value"}]
