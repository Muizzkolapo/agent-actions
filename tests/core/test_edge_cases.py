"""Edge case tests for RecordProcessor."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.core.record_processor import RecordProcessor
from agent_actions.core.types import ProcessingContext, ProcessingStatus


class TestRecordProcessorEdgeCases:
    """Test edge cases for RecordProcessor."""

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_empty_content_dict(self, mock_run, mock_prep, mock_guard):
        """Handles empty content dict."""
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({}, True)

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        item = {"content": {}, "source_guid": "guid-123"}
        content, source_guid, snapshot = processor._normalize_input(item, context)

        assert content == {}
        assert source_guid == "guid-123"

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_none_content(self, mock_guid):
        """Handles None content."""
        mock_guid.return_value = "guid-456"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        # None content should be accepted
        content, source_guid, snapshot = processor._normalize_input(None, context)

        assert content is None
        assert source_guid == "guid-456"
        assert snapshot is None

    def test_missing_source_guid_subsequent_stage(self):
        """Missing source_guid in subsequent-stage handled."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        item = {"content": {"text": "data"}}
        content, source_guid, snapshot = processor._normalize_input(item, context)

        assert content == {"text": "data"}
        assert source_guid is None

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
    @patch("agent_actions.utilities.correlation.VersionIdGenerator.add_version_correlation_id")
    @patch("agent_actions.utilities.field_management.FieldManager")
    def test_llm_returns_empty_list(
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
        """LLM returns empty list → SUCCESS with empty data."""
        mock_node_id.return_value = "node-123"
        mock_lineage.return_value = ["node-123"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ([], True)
        mock_transform.return_value = []
        mock_extract_meta.return_value = MagicMock(to_dict=lambda: {"tokens": 10})
        mock_loop_id.side_effect = lambda item, *args, **kwargs: item
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        item = {"content": {"text": "input"}, "source_guid": "guid-123"}
        result = processor.process(item, context)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.data == []

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
    @patch("agent_actions.utilities.correlation.VersionIdGenerator.add_version_correlation_id")
    @patch("agent_actions.utilities.field_management.FieldManager")
    def test_very_large_content_dict(
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
        """Handles very large content dict."""
        mock_guid.return_value = "guid-large"
        mock_node_id.return_value = "node-large"
        mock_lineage.return_value = ["node-large"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"processed": "data"}, True)
        mock_transform.return_value = [{"content": {"processed": "data"}}]
        mock_extract_meta.return_value = MagicMock(to_dict=lambda: {"tokens": 5000})
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-123",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.side_effect = lambda item, *args: item

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        # Create very large content dict
        large_content = {f"field_{i}": f"value_{i}" for i in range(1000)}
        result = processor.process(large_content, context)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.source_guid == "guid-large"
