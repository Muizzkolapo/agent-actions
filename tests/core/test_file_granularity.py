"""Tests for FILE granularity mode."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.processing.processor import RecordProcessor
from agent_actions.workflow.pipeline import ProcessingPipeline, PipelineConfig
from agent_actions.config.di.container import ProcessorFactory
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.errors import ConfigurationError


class TestFileGranularityValidation:
    """Test FILE granularity validation in RecordProcessor."""

    def test_file_granularity_allowed_for_kind_tool(self):
        """FILE granularity allowed when kind is 'tool'."""
        agent_config = {
            "granularity": "file",
            "kind": "tool",
        }

        # Should not raise
        processor = RecordProcessor(agent_config=agent_config, agent_name="test_tool")
        assert processor is not None

    def test_file_granularity_blocked_for_kind_llm(self):
        """FILE granularity blocked when kind is 'llm'."""
        agent_config = {
            "granularity": "file",
            "kind": "llm",
            "model_vendor": "anthropic",
        }

        with pytest.raises(ConfigurationError) as exc_info:
            RecordProcessor(agent_config=agent_config, agent_name="test_llm")

        assert "FILE granularity is only supported for tool actions" in str(exc_info.value)

    def test_file_granularity_blocked_when_kind_not_set(self):
        """FILE granularity blocked when kind is not set (defaults to llm behavior)."""
        agent_config = {
            "granularity": "file",
            "model_vendor": "anthropic",
        }

        with pytest.raises(ConfigurationError) as exc_info:
            RecordProcessor(agent_config=agent_config, agent_name="test_no_kind")

        assert "FILE granularity is only supported for tool actions" in str(exc_info.value)

    def test_file_granularity_with_guard_blocked(self):
        """FILE granularity with guard is blocked (guards not supported in FILE mode)."""
        agent_config = {
            "granularity": "file",
            "kind": "tool",
            "guard": {"clause": "status == 'active'", "behavior": "skip"},
        }

        with pytest.raises(ConfigurationError) as exc_info:
            RecordProcessor(agent_config=agent_config, agent_name="test_guard")

        assert "Guards are not supported with FILE granularity" in str(exc_info.value)

    def test_record_granularity_with_guard_allowed(self):
        """RECORD granularity with guard is allowed."""
        agent_config = {
            "granularity": "record",
            "kind": "tool",
            "guard": {"clause": "status == 'active'", "behavior": "skip"},
        }

        # Should not raise
        processor = RecordProcessor(agent_config=agent_config, agent_name="test_guard_record")
        assert processor is not None

    def test_record_granularity_allowed_for_all_kinds(self):
        """RECORD granularity allowed for any kind."""
        for kind in ["tool", "llm", ""]:
            agent_config = {
                "granularity": "record",
                "kind": kind,
            }

            # Should not raise
            processor = RecordProcessor(
                agent_config=agent_config, agent_name=f"test_{kind or 'empty'}"
            )
            assert processor is not None


class TestFileGranularityRouting:
    """Test routing logic in ProcessingPipeline."""

    @pytest.mark.skip(reason="Integration test - requires full generate flow setup")
    @patch(
        "agent_actions.orchestration.processing_pipeline.ProcessingPipeline._process_file_mode_tool"
    )
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    def test_routes_to_file_mode_handler(self, mock_reader, mock_file_handler):
        """FILE + TOOL routes to _process_file_mode_tool."""
        mock_file_handler.return_value = [
            ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                data=[{"result": "data"}],
                source_guid=None,
                raw_response=[{"result": "data"}],
                executed=True,
            )
        ]
        mock_reader.return_value.read_input_file.return_value = [
            {"input": "data1"},
            {"input": "data2"},
        ]

        # Create ProcessingPipeline with FILE granularity
        config = PipelineConfig(
            agent_config={
                "granularity": "file",
                "kind": "tool",
            },
            agent_name="test_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        processor_factory.create_processor.return_value = MagicMock()

        generator = ProcessingPipeline(config, processor_factory)

        # Mock dependencies
        generator.output_handler = MagicMock()
        generator.output_handler.save_main_output = MagicMock()

        # Call generate
        generator.generate(
            file_path="test.json",
            base_directory="/tmp",
            output_directory="/tmp/output",
            agent_indices={0: generator},
        )

        # Verify _process_file_mode_tool was called
        mock_file_handler.assert_called_once()

    @pytest.mark.skip(reason="Integration test - requires full generate flow setup")
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    def test_routes_to_record_mode_for_llm(self, mock_reader):
        """RECORD + LLM routes to process_batch."""
        mock_reader.return_value.read_input_file.return_value = [{"input": "data"}]

        # Create ProcessingPipeline with RECORD granularity
        config = PipelineConfig(
            agent_config={
                "granularity": "record",
                "model_vendor": "anthropic",
            },
            agent_name="test_llm",
            idx=0,
        )

        processor_factory = MagicMock()
        mock_processor = MagicMock()
        mock_processor.process_batch.return_value = [
            ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                data=[{"result": "data"}],
                source_guid="guid-1",
                raw_response={"result": "data"},
                executed=True,
            )
        ]
        processor_factory.create_processor.return_value = mock_processor

        generator = ProcessingPipeline(config, processor_factory)
        generator.record_processor = mock_processor

        # Mock dependencies
        generator.output_handler = MagicMock()
        generator.output_handler.save_main_output = MagicMock()

        # Call generate
        generator.generate(
            file_path="test.json",
            base_directory="/tmp",
            output_directory="/tmp/output",
            agent_indices={0: generator},
        )

        # Verify process_batch was called
        mock_processor.process_batch.assert_called_once()
