"""Tests for EnrichmentPipeline and enrichers."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.core.enrichment import (
    Enricher,
    EnrichmentPipeline,
    LineageEnricher,
    LoopIdEnricher,
    MetadataEnricher,
    PassthroughEnricher,
    RequiredFieldsEnricher,
)
from agent_actions.core.types import (
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

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    def test_generates_node_id_from_action_name(self, mock_build, mock_gen):
        """node_id generated using IDGenerator.generate_node_id(action_name)."""
        mock_gen.return_value = "action_uuid123"
        mock_build.return_value = ["action_uuid123"]

        enricher = LineageEnricher()
        result = ProcessingResult.success(data=[{"key": "value"}])
        context = ProcessingContext(agent_config={"agent_type": "transform"}, agent_name="test")

        enriched = enricher.enrich(result, context)

        mock_gen.assert_called_once_with("transform")
        assert enriched.node_id == "action_uuid123"

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    def test_single_item_gets_base_node_id(self, mock_build, mock_gen):
        """Single item: node_id = base_node_id (no suffix)."""
        mock_gen.return_value = "node_base"
        mock_build.return_value = ["node_base"]

        enricher = LineageEnricher()
        result = ProcessingResult.success(data=[{"key": "value"}])
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        assert enriched.data[0]["node_id"] == "node_base"

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    def test_multiple_items_get_indexed_node_ids(self, mock_build, mock_gen):
        """Multiple items: node_id = base_node_id_0, base_node_id_1, etc."""
        mock_gen.return_value = "node_base"
        mock_build.return_value = ["node_base_0"]

        enricher = LineageEnricher()
        result = ProcessingResult.success(data=[{"key": "val1"}, {"key": "val2"}])
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        assert enriched.data[0]["node_id"] == "node_base_0"
        assert enriched.data[1]["node_id"] == "node_base_1"

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.add_unified_lineage")
    def test_first_stage_passes_none_parent(self, mock_add_lineage, mock_gen):
        """First-stage: parent_item=None (no parent to chain)."""
        mock_gen.return_value = "node_123"
        mock_add_lineage.return_value = {"node_id": "node_123", "lineage": ["node_123"]}

        enricher = LineageEnricher()
        result = ProcessingResult.success(
            data=[{"content": {"text": "output"}}], source_guid="guid-123"
        )
        context = ProcessingContext(agent_config={}, agent_name="extract", is_first_stage=True)

        enriched = enricher.enrich(result, context)

        # Should call add_unified_lineage with parent_item=None
        mock_add_lineage.assert_called_once()
        call_args = mock_add_lineage.call_args
        assert call_args[1]["parent_item"] is None

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.add_unified_lineage")
    def test_subsequent_stage_chains_parent_lineage(self, mock_add_lineage, mock_gen):
        """Subsequent-stage: Looks up parent and chains lineage."""
        mock_gen.return_value = "transform_xyz"
        mock_add_lineage.return_value = {
            "node_id": "transform_xyz",
            "lineage": ["extract_abc", "transform_xyz"],
        }

        enricher = LineageEnricher()
        result = ProcessingResult.success(
            data=[{"content": {"text": "output"}}], source_guid="guid-123"
        )

        # Parent item in source_data
        parent_item = {
            "source_guid": "guid-123",
            "node_id": "extract_abc",
            "lineage": ["extract_abc"],
        }

        context = ProcessingContext(
            agent_config={},
            agent_name="transform",
            is_first_stage=False,
            source_data=[parent_item],
        )

        enriched = enricher.enrich(result, context)

        # Should call add_unified_lineage with parent_item from source_data
        mock_add_lineage.assert_called_once()
        call_args = mock_add_lineage.call_args
        assert call_args[1]["parent_item"] == parent_item

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.add_unified_lineage")
    def test_missing_parent_graceful_fallback(self, mock_add_lineage, mock_gen):
        """Subsequent-stage with missing parent: Falls back to parent_item=None."""
        mock_gen.return_value = "transform_xyz"
        mock_add_lineage.return_value = {
            "node_id": "transform_xyz",
            "lineage": ["transform_xyz"],
        }

        enricher = LineageEnricher()
        result = ProcessingResult.success(
            data=[{"content": {"text": "output"}}],
            source_guid="guid-999",  # Not in source_data
        )

        context = ProcessingContext(
            agent_config={},
            agent_name="transform",
            is_first_stage=False,
            source_data=[
                {
                    "source_guid": "guid-123",
                    "node_id": "extract_abc",
                    "lineage": ["extract_abc"],
                }
            ],
        )

        enriched = enricher.enrich(result, context)

        # Should call add_unified_lineage with parent_item=None (graceful fallback)
        mock_add_lineage.assert_called_once()
        call_args = mock_add_lineage.call_args
        assert call_args[1]["parent_item"] is None

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.add_unified_lineage")
    def test_empty_source_data_graceful_fallback(self, mock_add_lineage, mock_gen):
        """Subsequent-stage with empty source_data: Falls back to parent_item=None."""
        mock_gen.return_value = "transform_xyz"
        mock_add_lineage.return_value = {
            "node_id": "transform_xyz",
            "lineage": ["transform_xyz"],
        }

        enricher = LineageEnricher()
        result = ProcessingResult.success(
            data=[{"content": {"text": "output"}}], source_guid="guid-123"
        )

        context = ProcessingContext(
            agent_config={},
            agent_name="transform",
            is_first_stage=False,
            source_data=[],  # Empty source_data
        )

        enriched = enricher.enrich(result, context)

        # Should call add_unified_lineage with parent_item=None
        mock_add_lineage.assert_called_once()
        call_args = mock_add_lineage.call_args
        assert call_args[1]["parent_item"] is None


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

    @patch("agent_actions.utilities.metadata.MetadataExtractor.extract_from_response")
    @patch("agent_actions.utilities.field_management.FieldManager.add_metadata")
    def test_extracts_metadata_from_raw_response(self, mock_add, mock_extract):
        """MetadataExtractor.extract_from_response called with raw_response."""
        mock_metadata = MagicMock()
        mock_metadata.to_dict.return_value = {"model": "gpt-4", "tokens": 100}
        mock_extract.return_value = mock_metadata

        enricher = MetadataEnricher()
        result = ProcessingResult.success(
            data=[{"key": "value"}], raw_response={"text": "response"}
        )
        context = ProcessingContext(agent_config={"model": "gpt-4"}, agent_name="test")

        enriched = enricher.enrich(result, context)

        mock_extract.assert_called_once_with(
            response={"text": "response"}, agent_config={"model": "gpt-4"}
        )

    @patch("agent_actions.utilities.metadata.MetadataExtractor.extract_from_response")
    @patch("agent_actions.utilities.field_management.FieldManager.add_metadata")
    def test_adds_metadata_to_each_item(self, mock_add, mock_extract):
        """FieldManager.add_metadata called for each item in data."""
        mock_metadata = MagicMock()
        mock_metadata.to_dict.return_value = {"model": "gpt-4"}
        mock_extract.return_value = mock_metadata

        enricher = MetadataEnricher()
        result = ProcessingResult.success(data=[{"item": 1}, {"item": 2}])
        context = ProcessingContext(agent_config={}, agent_name="test")

        enricher.enrich(result, context)

        assert mock_add.call_count == 2


class TestLoopIdEnricher:
    """Test LoopIdEnricher."""

    def test_skips_filtered_results(self):
        """FILTERED status → no loop ID added."""
        enricher = LoopIdEnricher()
        result = ProcessingResult.filtered()
        context = ProcessingContext(agent_config={}, agent_name="test")

        enriched = enricher.enrich(result, context)

        assert enriched.data == []

    @patch("agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id")
    def test_adds_loop_correlation_id_to_each_item(self, mock_add):
        """LoopIdGenerator.add_loop_correlation_id called per item."""
        mock_add.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop_123",
        }

        enricher = LoopIdEnricher()
        result = ProcessingResult.success(data=[{"key": "value"}])
        context = ProcessingContext(
            agent_config={"loop_id": "parent_loop"}, agent_name="test", record_index=5
        )

        enriched = enricher.enrich(result, context)

        mock_add.assert_called_once()
        assert "loop_id" in enriched.data[0]

    @patch("agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id")
    def test_uses_record_index_from_context(self, mock_add):
        """record_index from context passed to LoopIdGenerator."""
        mock_add.return_value = {"key": "value", "loop_id": "loop_123"}

        enricher = LoopIdEnricher()
        result = ProcessingResult.success(data=[{"key": "value"}])
        context = ProcessingContext(agent_config={}, agent_name="test", record_index=42)

        enricher.enrich(result, context)

        # Check that record_index=42 was passed
        call_kwargs = mock_add.call_args[1]
        assert call_kwargs["record_index"] == 42


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

    @patch("agent_actions.utilities.field_management.FieldManager")
    def test_calls_ensure_required_fields(self, mock_manager_class):
        """FieldManager().ensure_required_fields called per item."""
        mock_instance = MagicMock()
        mock_manager_class.return_value = mock_instance
        mock_instance.ensure_required_fields.return_value = {"key": "value"}

        enricher = RequiredFieldsEnricher()
        result = ProcessingResult.success(data=[{"key": "value"}], source_guid="guid-123")
        context = ProcessingContext(agent_config={}, agent_name="test")

        enricher.enrich(result, context)

        mock_instance.ensure_required_fields.assert_called_once_with(
            {"key": "value"}, "guid-123", 0
        )


class TestEnrichmentPipeline:
    """Test EnrichmentPipeline."""

    def test_default_enricher_order(self):
        """Default order: Lineage → Metadata → LoopId → Passthrough → RequiredFields."""
        pipeline = EnrichmentPipeline()

        assert len(pipeline.enrichers) == 5
        assert isinstance(pipeline.enrichers[0], LineageEnricher)
        assert isinstance(pipeline.enrichers[1], MetadataEnricher)
        assert isinstance(pipeline.enrichers[2], LoopIdEnricher)
        assert isinstance(pipeline.enrichers[3], PassthroughEnricher)
        assert isinstance(pipeline.enrichers[4], RequiredFieldsEnricher)

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
