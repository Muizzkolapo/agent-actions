"""Integration tests for subsequent-stage processing (TargetContentProcessor replacement)."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.core.record_processor import RecordProcessor
from agent_actions.core.types import ProcessingContext, ProcessingMode, ProcessingStatus


class TestSubsequentStageStructuredInput:
    """Test subsequent-stage with structured input."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    @patch("agent_actions.utilities.processor.processor_helpers.transform_with_passthrough")
    @patch("agent_actions.utilities.metadata.MetadataExtractor.extract_from_response")
    @patch("agent_actions.utilities.field_management.FieldManager.add_metadata")
    @patch("agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id")
    @patch("agent_actions.utilities.field_management.FieldManager")
    def test_structured_input_content_and_guid(
        self,
        mock_field_mgr,
        mock_loop_id,
        mock_add_meta,
        mock_extract_meta,
        mock_transform,
        mock_run,
        mock_prep,
        mock_guard,
        mock_lineage,
        mock_node_id,
    ):
        """Structured input {content, source_guid} processed correctly."""
        mock_node_id.return_value = "node-123"
        mock_lineage.return_value = ["node-123"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"result": "data"}, True)
        mock_transform.return_value = [{"content": {"output": "value"}}]
        mock_extract_meta.return_value = MagicMock(to_dict=lambda: {"tokens": 100})
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-123",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.return_value = {"content": {"output": "value"}}

        processor = RecordProcessor(agent_config={}, agent_name="enrich")
        context = ProcessingContext(agent_config={}, agent_name="enrich", is_first_stage=False)

        item = {"content": {"text": "input"}, "source_guid": "guid-456"}
        result = processor.process(item, context)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.source_guid == "guid-456"


class TestSubsequentStageSourceLookup:
    """Test source data lookup by GUID."""

    @patch(
        "agent_actions.preprocessing.transformation.data_transformer.DataTransformer.get_content_by_source_guid"
    )
    def test_source_data_lookup_by_guid(self, mock_get):
        """Looks up source content by source_guid."""
        mock_get.return_value = {"source": "content"}

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={},
            agent_name="test",
            is_first_stage=False,
            source_data=[{"source_guid": "guid-123", "content": {"source": "content"}}],
        )

        result = processor._get_source_content("guid-123", context)

        mock_get.assert_called_once_with(
            [{"source_guid": "guid-123", "content": {"source": "content"}}], "guid-123"
        )
        assert result == {"source": "content"}


class TestSubsequentStagePassthroughFields:
    """Test passthrough fields merged."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    @patch("agent_actions.utilities.processor.processor_helpers.transform_with_passthrough")
    @patch("agent_actions.utilities.metadata.MetadataExtractor.extract_from_response")
    @patch("agent_actions.utilities.field_management.FieldManager.add_metadata")
    @patch("agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id")
    @patch("agent_actions.utilities.field_management.FieldManager")
    def test_passthrough_fields_merged(
        self,
        mock_field_mgr,
        mock_loop_id,
        mock_add_meta,
        mock_extract_meta,
        mock_transform,
        mock_run,
        mock_prep,
        mock_guard,
        mock_lineage,
        mock_node_id,
    ):
        """Passthrough fields merged into output content."""
        mock_node_id.return_value = "node-123"
        mock_lineage.return_value = ["node-123"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(
            formatted_prompt="prompt", passthrough_fields={"extra": "field"}
        )
        mock_run.return_value = ({"result": "data"}, True)
        mock_transform.return_value = [{"content": {"output": "value"}}]
        mock_extract_meta.return_value = MagicMock(to_dict=lambda: {"tokens": 50})
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-123",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.return_value = {
            "content": {"output": "value", "extra": "field"}
        }

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        item = {"content": {"text": "input"}, "source_guid": "guid-123"}
        result = processor.process(item, context)

        assert result.passthrough_fields == {"extra": "field"}


class TestSubsequentStageLoopCorrelation:
    """Test loop correlation ID added."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    @patch("agent_actions.utilities.processor.processor_helpers.transform_with_passthrough")
    @patch("agent_actions.utilities.metadata.MetadataExtractor.extract_from_response")
    @patch("agent_actions.utilities.field_management.FieldManager.add_metadata")
    @patch("agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id")
    @patch("agent_actions.utilities.field_management.FieldManager")
    def test_loop_correlation_id_added(
        self,
        mock_field_mgr,
        mock_loop_id,
        mock_add_meta,
        mock_extract_meta,
        mock_transform,
        mock_run,
        mock_prep,
        mock_guard,
        mock_lineage,
        mock_node_id,
    ):
        """Loop correlation ID added to output items."""
        mock_node_id.return_value = "node-123"
        mock_lineage.return_value = ["node-123"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"result": "data"}, True)
        mock_transform.return_value = [{"content": {"text": "output"}}]
        mock_extract_meta.return_value = MagicMock(to_dict=lambda: {"tokens": 50})
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-456",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.return_value = {"content": {"text": "output"}}

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={}, agent_name="test", is_first_stage=False, record_index=5
        )

        item = {"content": {"text": "input"}, "source_guid": "guid-123"}
        result = processor.process(item, context)

        mock_loop_id.assert_called()


class TestSubsequentStageGuardBehavior:
    """Test guard behavior in subsequent-stage."""

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_guard_skip_preserves_input(self, mock_guard):
        """Guard skip → preserves input in SKIPPED result."""
        mock_guard.return_value = (False, "skip")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={"guard": {"clause": "False", "behavior": "skip"}},
            agent_name="test",
            is_first_stage=False,
        )

        item = {"content": {"text": "input"}, "source_guid": "guid-123"}
        result = processor.process(item, context)

        assert result.status == ProcessingStatus.SKIPPED
        assert result.data[0] == {"text": "input"}

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_guard_filter_excludes_from_output(self, mock_guard):
        """Guard filter → returns FILTERED result."""
        mock_guard.return_value = (False, "filter")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={"guard": {"clause": "False", "behavior": "filter"}},
            agent_name="test",
            is_first_stage=False,
        )

        item = {"content": {"text": "input"}, "source_guid": "guid-123"}
        result = processor.process(item, context)

        assert result.status == ProcessingStatus.FILTERED
        assert result.data == []


class TestSubsequentStageSplitRecords:
    """Test split records get indexed node IDs."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    @patch("agent_actions.utilities.processor.processor_helpers.transform_with_passthrough")
    @patch("agent_actions.utilities.metadata.MetadataExtractor.extract_from_response")
    @patch("agent_actions.utilities.field_management.FieldManager.add_metadata")
    @patch("agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id")
    @patch("agent_actions.utilities.field_management.FieldManager")
    def test_split_records_indexed_node_ids(
        self,
        mock_field_mgr,
        mock_loop_id,
        mock_add_meta,
        mock_extract_meta,
        mock_transform,
        mock_run,
        mock_prep,
        mock_guard,
        mock_lineage,
        mock_node_id,
    ):
        """Split records (1→many) get indexed node_ids."""
        mock_node_id.return_value = "node-base"
        mock_lineage.return_value = ["node-base_0"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ([{"item": 1}, {"item": 2}], True)
        mock_transform.return_value = [
            {"content": {"item": 1}},
            {"content": {"item": 2}},
        ]
        mock_extract_meta.return_value = MagicMock(to_dict=lambda: {"tokens": 100})
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-123",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.side_effect = lambda item, *args: item

        processor = RecordProcessor(agent_config={}, agent_name="split")
        context = ProcessingContext(agent_config={}, agent_name="split", is_first_stage=False)

        item = {"content": {"text": "input"}, "source_guid": "guid-123"}
        result = processor.process(item, context)

        # Should have 2 items with indexed node_ids
        assert len(result.data) == 2
        assert result.data[0]["node_id"] == "node-base_0"
        assert result.data[1]["node_id"] == "node-base_1"


class TestSubsequentStageMetadata:
    """Test metadata added correctly in subsequent-stage."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    @patch("agent_actions.utilities.processor.processor_helpers.transform_with_passthrough")
    @patch("agent_actions.utilities.metadata.MetadataExtractor.extract_from_response")
    @patch("agent_actions.utilities.field_management.FieldManager.add_metadata")
    @patch("agent_actions.utilities.correlation.LoopIdGenerator.add_loop_correlation_id")
    @patch("agent_actions.utilities.field_management.FieldManager")
    def test_metadata_added_correctly(
        self,
        mock_field_mgr,
        mock_loop_id,
        mock_add_meta,
        mock_extract_meta,
        mock_transform,
        mock_run,
        mock_prep,
        mock_guard,
        mock_lineage,
        mock_node_id,
    ):
        """Metadata extracted and added to subsequent-stage output."""
        mock_node_id.return_value = "node-123"
        mock_lineage.return_value = ["node-123"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"result": "data"}, True)
        mock_transform.return_value = [{"content": {"text": "output"}}]
        mock_extract_meta.return_value = MagicMock(
            to_dict=lambda: {"model": "gpt-4", "tokens": 150}
        )
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-123",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.return_value = {"content": {"text": "output"}}

        processor = RecordProcessor(agent_config={"model": "gpt-4"}, agent_name="test")
        context = ProcessingContext(
            agent_config={"model": "gpt-4"}, agent_name="test", is_first_stage=False
        )

        item = {"content": {"text": "input"}, "source_guid": "guid-123"}
        result = processor.process(item, context)

        mock_extract_meta.assert_called_once()
        mock_add_meta.assert_called()


class TestSubsequentStageEmptyContent:
    """Test handling of empty content."""

    def test_empty_content_handling(self):
        """Handles empty content dict."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        content, source_guid, snapshot = processor._normalize_input(
            {"content": {}, "source_guid": "guid-123"}, context
        )

        assert content == {}
        assert source_guid == "guid-123"
        assert snapshot is None


class TestSubsequentStageMissingSourceGUID:
    """Test handling of missing source_guid."""

    def test_missing_source_guid_handling(self):
        """Handles missing source_guid field."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        content, source_guid, snapshot = processor._normalize_input(
            {"content": {"text": "data"}}, context
        )

        assert content == {"text": "data"}
        assert source_guid is None
        assert snapshot is None


class TestSubsequentStageBatchProcessing:
    """Test batch processing in subsequent-stage."""

    @patch.object(RecordProcessor, "process")
    def test_multiple_items_batch_processing(self, mock_process):
        """Batch processes multiple subsequent-stage items."""
        mock_process.side_effect = [
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 1}]),
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 2}]),
        ]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        items = [
            {"content": {"text": "item 1"}, "source_guid": "guid-1"},
            {"content": {"text": "item 2"}, "source_guid": "guid-2"},
        ]

        results = processor.process_batch(items, context)

        assert len(results) == 2
        assert mock_process.call_count == 2
