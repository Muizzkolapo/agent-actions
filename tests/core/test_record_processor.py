"""Tests for RecordProcessor."""

from unittest.mock import patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)


class TestBatchProcessing:
    """Test process_batch method."""

    @patch.object(RecordProcessor, "process")
    def test_processes_multiple_items(self, mock_process):
        """Batch processing calls process() for each item."""
        mock_process.side_effect = [
            ProcessingResult.success(data=[{"item": 1}]),
            ProcessingResult.success(data=[{"item": 2}]),
        ]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        results = processor.process_batch([{"key": "val1"}, {"key": "val2"}], context)

        assert len(results) == 2
        assert mock_process.call_count == 2

    @patch.object(RecordProcessor, "process")
    def test_updates_record_index_per_item(self, mock_process):
        """Batch processing updates record_index in context."""
        mock_process.return_value = ProcessingResult.success(data=[{"item": 1}])

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", record_index=0)

        processor.process_batch([{"key": "val1"}, {"key": "val2"}], context)

        # Check record_index was updated in context
        call_contexts = [call[0][1] for call in mock_process.call_args_list]
        assert call_contexts[0].record_index == 0
        assert call_contexts[1].record_index == 1

    @patch.object(RecordProcessor, "process")
    def test_handles_exception_creates_failed_result(self, mock_process):
        """Exception in process() creates ProcessingResult.failed()."""
        mock_process.side_effect = [
            ProcessingResult.success(data=[{"item": 1}]),
            Exception("Processing failed"),
            ProcessingResult.success(data=[{"item": 3}]),
        ]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        results = processor.process_batch(
            [{"key": "val1"}, {"key": "val2"}, {"key": "val3"}], context
        )

        assert len(results) == 3
        assert results[0].status == ProcessingStatus.SUCCESS
        assert results[1].status == ProcessingStatus.FAILED
        assert "Error processing item 1" in results[1].error
        assert "Processing failed" in results[1].error
        assert results[2].status == ProcessingStatus.SUCCESS

    @patch.object(RecordProcessor, "process")
    def test_continues_processing_after_failure(self, mock_process):
        """Batch continues processing remaining items after failure."""
        mock_process.side_effect = [
            Exception("First item failed"),
            ProcessingResult.success(data=[{"item": 2}]),
            Exception("Third item failed"),
            ProcessingResult.success(data=[{"item": 4}]),
        ]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        results = processor.process_batch(
            [{"key": "val1"}, {"key": "val2"}, {"key": "val3"}, {"key": "val4"}],
            context,
        )

        # All 4 items processed despite failures
        assert len(results) == 4
        assert results[0].status == ProcessingStatus.FAILED
        assert results[1].status == ProcessingStatus.SUCCESS
        assert results[2].status == ProcessingStatus.FAILED
        assert results[3].status == ProcessingStatus.SUCCESS

    @patch.object(RecordProcessor, "process")
    def test_captures_source_guid_in_failed_result(self, mock_process):
        """Failed result includes source_guid if available."""
        mock_process.side_effect = Exception("Processing failed")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        results = processor.process_batch([{"source_guid": "guid-123", "content": "data"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert results[0].source_guid == "guid-123"


class TestConfigurationErrorHandling:
    """Test that ConfigurationError is re-raised and fails the workflow."""

    def test_configuration_error_is_reraised(self):
        """Test that ConfigurationError is not caught and re-raised immediately."""
        from agent_actions.errors import ConfigurationError

        class FailingProcessor(RecordProcessor):
            def process(self, item, context):
                raise ConfigurationError(
                    "Dependency 'dep_A' not in context_scope", context={"action": "test_action"}
                )

        processor = FailingProcessor(agent_config={}, agent_name="test_action")
        context = ProcessingContext(
            agent_config={},
            agent_name="test_action",
            agent_indices={"test_action": 0},
            is_first_stage=False,
            mode=RunMode.BATCH,
        )

        # ConfigurationError should be re-raised, not caught
        with pytest.raises(ConfigurationError) as exc_info:
            processor.process_batch([{"data": "test"}], context)

        assert "not in context_scope" in str(exc_info.value)

    def test_template_variable_error_is_reraised(self):
        """Test that TemplateVariableError is re-raised immediately (code bug, not data error)."""
        from jinja2 import UndefinedError

        from agent_actions.errors.operations import TemplateVariableError

        class FailingProcessor(RecordProcessor):
            def process(self, item, context):
                raise TemplateVariableError(
                    missing_variables=["page_content"],
                    available_variables=["source", "loop"],
                    agent_name="test_action",
                    mode="batch",
                    cause=UndefinedError("'page_content' is undefined"),
                )

        processor = FailingProcessor(agent_config={}, agent_name="test_action")
        context = ProcessingContext(
            agent_config={},
            agent_name="test_action",
            agent_indices={"test_action": 0},
            is_first_stage=False,
            mode=RunMode.BATCH,
        )

        # TemplateVariableError should be re-raised, not caught
        with pytest.raises(TemplateVariableError) as exc_info:
            processor.process_batch([{"data": "test"}], context)

        assert "page_content" in str(exc_info.value)

    def test_other_exceptions_create_failed_results(self):
        """Test that non-ConfigurationError exceptions create failed results."""

        class FailingProcessor(RecordProcessor):
            def process(self, item, context):
                raise ValueError("Some transient error")

        processor = FailingProcessor(agent_config={}, agent_name="test_action")
        context = ProcessingContext(
            agent_config={},
            agent_name="test_action",
            agent_indices={"test_action": 0},
            is_first_stage=False,
            mode=RunMode.BATCH,
        )

        # Other exceptions should be caught and converted to failed results
        results = processor.process_batch([{"data": "test"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert "Some transient error" in results[0].error
