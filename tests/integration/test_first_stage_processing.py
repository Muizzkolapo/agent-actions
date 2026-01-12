"""Integration tests for first-stage processing (StagingProcessor replacement)."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.core.record_processor import RecordProcessor
from agent_actions.core.types import ProcessingContext, ProcessingMode, ProcessingStatus


class TestFirstStageRawTextProcessing:
    """Test first-stage processing with raw text input."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
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
    def test_raw_text_to_structured_output(
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
        mock_guid,
    ):
        """Raw text input → structured output with lineage."""
        # Setup mocks
        mock_guid.return_value = "source-guid-123"
        mock_node_id.return_value = "node-456"
        mock_lineage.return_value = ["node-456"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"generated": "text"}, True)
        mock_transform.return_value = [{"content": {"text": "generated text"}}]
        mock_extract_meta.return_value = MagicMock(
            to_dict=lambda: {"model": "gpt-4", "tokens": 100}
        )
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-123",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.return_value = {
            "content": {"text": "generated text"}
        }

        processor = RecordProcessor(agent_config={}, agent_name="extract")
        context = ProcessingContext(agent_config={}, agent_name="extract", is_first_stage=True)

        result = processor.process("This is raw text input", context)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.source_guid == "source-guid-123"
        assert result.node_id == "node-456"
        assert result.source_snapshot == "This is raw text input"
        assert len(result.data) > 0


class TestFirstStageJSONProcessing:
    """Test first-stage processing with raw JSON input."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
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
    def test_raw_json_to_structured_output(
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
        mock_guid,
    ):
        """Raw JSON input → structured output."""
        # Setup mocks
        mock_guid.return_value = "source-guid-456"
        mock_node_id.return_value = "node-789"
        mock_lineage.return_value = ["node-789"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"extracted": "data"}, True)
        mock_transform.return_value = [{"content": {"key": "value"}}]
        mock_extract_meta.return_value = MagicMock(to_dict=lambda: {"tokens": 50})
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-456",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.return_value = {"content": {"key": "value"}}

        processor = RecordProcessor(agent_config={}, agent_name="transform")
        context = ProcessingContext(agent_config={}, agent_name="transform", is_first_stage=True)

        input_data = {"name": "John", "age": 30}
        result = processor.process(input_data, context)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.source_guid == "source-guid-456"
        assert result.source_snapshot == {"name": "John", "age": 30}


class TestFirstStageSourceSnapshot:
    """Test source snapshot preservation."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_source_snapshot_preserved(self, mock_guid):
        """Source snapshot preserved in result."""
        mock_guid.return_value = "guid-123"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        input_data = {"text": "source content", "metadata": {"page": 1}}
        _, _, snapshot = processor._normalize_input(input_data, context)

        assert snapshot == {"text": "source content", "metadata": {"page": 1}}

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_chunk_info_filtering_in_snapshot(self, mock_guid):
        """chunk_info metadata keys filtered from snapshot."""
        mock_guid.return_value = "guid-456"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        input_data = {
            "chunk_info": {"page": 1, "chunk": 0},
            "target_id": "target-123",
            "record_index": 5,
            "chunk_index": 2,
            "text": "content",
        }

        _, _, snapshot = processor._normalize_input(input_data, context)

        assert "target_id" not in snapshot
        assert "record_index" not in snapshot
        assert "chunk_index" not in snapshot
        assert "chunk_info" in snapshot
        assert "text" in snapshot


class TestFirstStageDeterministicGUID:
    """Test deterministic GUID generation."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_generates_deterministic_guid(self, mock_guid):
        """Generates deterministic source_guid for input."""
        mock_guid.return_value = "deterministic-guid-789"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        input_data = {"key": "value"}
        _, source_guid, _ = processor._normalize_input(input_data, context)

        mock_guid.assert_called_once_with({"key": "value"})
        assert source_guid == "deterministic-guid-789"


class TestFirstStageGuardBehavior:
    """Test guard behavior in first-stage."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_guard_skip_behavior(self, mock_guard, mock_guid):
        """Guard skip → preserves input in SKIPPED result."""
        mock_guid.return_value = "guid-123"
        mock_guard.return_value = (False, "skip")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={"guard": {"clause": "False", "behavior": "skip"}},
            agent_name="test",
            is_first_stage=True,
        )

        result = processor.process({"text": "input"}, context)

        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "guard_skip"

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_guard_filter_behavior(self, mock_guard, mock_guid):
        """Guard filter → returns FILTERED result."""
        mock_guid.return_value = "guid-456"
        mock_guard.return_value = (False, "filter")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={"guard": {"clause": "False", "behavior": "filter"}},
            agent_name="test",
            is_first_stage=True,
        )

        result = processor.process({"text": "input"}, context)

        assert result.status == ProcessingStatus.FILTERED
        assert result.data == []


class TestFirstStageMetadata:
    """Test metadata added correctly in first-stage."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
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
    def test_metadata_added_to_output(
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
        mock_guid,
    ):
        """Metadata extracted from response and added to output."""
        mock_guid.return_value = "guid-123"
        mock_node_id.return_value = "node-456"
        mock_lineage.return_value = ["node-456"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"response": "data"}, True)
        mock_transform.return_value = [{"content": {"text": "output"}}]
        mock_extract_meta.return_value = MagicMock(
            to_dict=lambda: {"model": "gpt-4", "tokens": 200}
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
            agent_config={"model": "gpt-4"}, agent_name="test", is_first_stage=True
        )

        result = processor.process({"text": "input"}, context)

        mock_extract_meta.assert_called_once()
        mock_add_meta.assert_called()


class TestFirstStageBatchProcessing:
    """Test batch processing in first-stage."""

    @patch.object(RecordProcessor, "process")
    def test_multiple_items_batch_processing(self, mock_process):
        """Batch processes multiple first-stage items."""
        mock_process.side_effect = [
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 1}]),
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 2}]),
            MagicMock(status=ProcessingStatus.SUCCESS, data=[{"item": 3}]),
        ]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        items = [
            {"text": "item 1"},
            {"text": "item 2"},
            {"text": "item 3"},
        ]

        results = processor.process_batch(items, context)

        assert len(results) == 3
        assert mock_process.call_count == 3
