"""Tests for FILE granularity mode."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.core.record_processor import RecordProcessor
from agent_actions.orchestration.target_generator import TargetGenerator, GeneratorConfig
from agent_actions.orchestration.dependency_injection import ProcessorFactory
from agent_actions.core.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.errors import ConfigurationError


class TestFileGranularityValidation:
    """Test FILE granularity validation in RecordProcessor."""

    def test_file_granularity_allowed_for_tools(self):
        """FILE granularity allowed when model_vendor is 'tool'."""
        agent_config = {
            "granularity": "file",
            "model_vendor": "tool",
        }

        # Should not raise
        processor = RecordProcessor(agent_config=agent_config, agent_name="test_tool")
        assert processor is not None

    def test_file_granularity_blocked_for_llm(self):
        """FILE granularity blocked when model_vendor is not 'tool'."""
        agent_config = {
            "granularity": "file",
            "model_vendor": "anthropic",
        }

        with pytest.raises(ConfigurationError) as exc_info:
            RecordProcessor(agent_config=agent_config, agent_name="test_llm")

        assert "FILE granularity is only supported for tool actions" in str(exc_info.value)
        assert "issues/740" in str(exc_info.value)

    def test_file_granularity_blocked_when_no_vendor(self):
        """FILE granularity blocked when model_vendor is missing."""
        agent_config = {
            "granularity": "file",
        }

        with pytest.raises(ConfigurationError) as exc_info:
            RecordProcessor(agent_config=agent_config, agent_name="test_missing")

        assert "FILE granularity is only supported for tool actions" in str(exc_info.value)

    def test_record_granularity_allowed_for_all(self):
        """RECORD granularity allowed for any model_vendor."""
        for vendor in ["tool", "anthropic", "openai", ""]:
            agent_config = {
                "granularity": "record",
                "model_vendor": vendor,
            }

            # Should not raise
            processor = RecordProcessor(agent_config=agent_config, agent_name=f"test_{vendor}")
            assert processor is not None


class TestFileGranularityRouting:
    """Test routing logic in TargetGenerator."""

    @pytest.mark.skip(reason="Integration test - requires full generate flow setup")
    @patch("agent_actions.orchestration.target_generator.TargetGenerator._process_file_mode_tool")
    @patch("agent_actions.orchestration.target_generator.FileReader")
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

        # Create TargetGenerator with FILE granularity
        config = GeneratorConfig(
            agent_config={
                "granularity": "file",
                "model_vendor": "tool",
            },
            agent_name="test_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        processor_factory.create_processor.return_value = MagicMock()

        generator = TargetGenerator(config, processor_factory)

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
    @patch("agent_actions.orchestration.target_generator.FileReader")
    def test_routes_to_record_mode_for_llm(self, mock_reader):
        """RECORD + LLM routes to process_batch."""
        mock_reader.return_value.read_input_file.return_value = [{"input": "data"}]

        # Create TargetGenerator with RECORD granularity
        config = GeneratorConfig(
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

        generator = TargetGenerator(config, processor_factory)
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


class TestFileModeTool:
    """Test _process_file_mode_tool method."""

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_invokes_tool_with_full_array(self, mock_run):
        """Tool receives full array in FILE mode."""
        # Mock run_dynamic_agent to return array
        mock_run.return_value = ([{"output": "1"}, {"output": "2"}], True)

        config = GeneratorConfig(
            agent_config={
                "granularity": "file",
                "model_vendor": "tool",
                "tools_path": "/path/to/tool",
            },
            agent_name="test_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        mock_processor = MagicMock()
        mock_enrichment = MagicMock()
        mock_enrichment.enrich.return_value = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"output": "1", "target_id": "new1"}, {"output": "2", "target_id": "new2"}],
            source_guid=None,
            raw_response=[{"output": "1"}, {"output": "2"}],
            executed=True,
        )
        mock_processor.enrichment_pipeline = mock_enrichment
        processor_factory.create_processor.return_value = mock_processor

        generator = TargetGenerator(config, processor_factory)
        generator.record_processor = mock_processor

        # Create context
        context = ProcessingContext(
            agent_config=config.agent_config,
            agent_name="test_tool",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        # Call _process_file_mode_tool
        input_data = [{"input": "a"}, {"input": "b"}]
        results = generator._process_file_mode_tool(input_data, context)

        # Verify run_dynamic_agent called with full array
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[1]["context"] == input_data  # Full array passed
        assert call_args[1]["agent_config"] == config.agent_config
        assert call_args[1]["tools_path"] == "/path/to/tool"

        # Verify results
        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS
        assert len(results[0].data) == 2

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_handles_n_to_m_transformation(self, mock_run):
        """Tool can transform N inputs to M outputs (e.g., 1→4)."""
        # Tool returns 4 outputs from 1 input
        mock_run.return_value = (
            [
                {"question": "q1"},
                {"question": "q2"},
                {"question": "q3"},
                {"question": "q4"},
            ],
            True,
        )

        config = GeneratorConfig(
            agent_config={
                "granularity": "file",
                "model_vendor": "tool",
            },
            agent_name="flatten_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        mock_processor = MagicMock()
        mock_enrichment = MagicMock()
        # Enrichment assigns new IDs to each output
        mock_enrichment.enrich.return_value = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"question": "q1", "target_id": "id1", "node_id": "flatten_123"},
                {"question": "q2", "target_id": "id2", "node_id": "flatten_123"},
                {"question": "q3", "target_id": "id3", "node_id": "flatten_123"},
                {"question": "q4", "target_id": "id4", "node_id": "flatten_123"},
            ],
            source_guid=None,
            raw_response=[
                {"question": "q1"},
                {"question": "q2"},
                {"question": "q3"},
                {"question": "q4"},
            ],
            executed=True,
        )
        mock_processor.enrichment_pipeline = mock_enrichment
        processor_factory.create_processor.return_value = mock_processor

        generator = TargetGenerator(config, processor_factory)
        generator.record_processor = mock_processor

        context = ProcessingContext(
            agent_config=config.agent_config,
            agent_name="flatten_tool",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        # 1 input record
        input_data = [{"doc": "has multiple questions"}]
        results = generator._process_file_mode_tool(input_data, context)

        # 4 output records
        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS
        assert len(results[0].data) == 4
        # Each has unique ID
        assert all("target_id" in item for item in results[0].data)

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_error_if_tool_returns_non_array(self, mock_run):
        """Error if tool returns non-array in FILE mode."""
        mock_run.return_value = ({"not": "array"}, True)

        config = GeneratorConfig(
            agent_config={
                "granularity": "file",
                "model_vendor": "tool",
            },
            agent_name="bad_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        mock_processor = MagicMock()
        processor_factory.create_processor.return_value = mock_processor

        generator = TargetGenerator(config, processor_factory)
        generator.record_processor = mock_processor

        context = ProcessingContext(
            agent_config=config.agent_config,
            agent_name="bad_tool",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        results = generator._process_file_mode_tool([{"input": "data"}], context)

        # Should return error result
        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert "must return array" in results[0].error

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_handles_empty_array(self, mock_run):
        """Handles empty array gracefully."""
        mock_run.return_value = ([], True)

        config = GeneratorConfig(
            agent_config={
                "granularity": "file",
                "model_vendor": "tool",
            },
            agent_name="filter_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        mock_processor = MagicMock()
        mock_enrichment = MagicMock()
        mock_enrichment.enrich.return_value = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[],
            source_guid=None,
            raw_response=[],
            executed=True,
        )
        mock_processor.enrichment_pipeline = mock_enrichment
        processor_factory.create_processor.return_value = mock_processor

        generator = TargetGenerator(config, processor_factory)
        generator.record_processor = mock_processor

        context = ProcessingContext(
            agent_config=config.agent_config,
            agent_name="filter_tool",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        results = generator._process_file_mode_tool([{"input": "data"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS
        assert len(results[0].data) == 0

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_handles_tool_exception(self, mock_run):
        """Handles exception from tool gracefully."""
        mock_run.side_effect = Exception("Tool execution failed")

        config = GeneratorConfig(
            agent_config={
                "granularity": "file",
                "model_vendor": "tool",
            },
            agent_name="failing_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        mock_processor = MagicMock()
        processor_factory.create_processor.return_value = mock_processor

        generator = TargetGenerator(config, processor_factory)
        generator.record_processor = mock_processor

        context = ProcessingContext(
            agent_config=config.agent_config,
            agent_name="failing_tool",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        results = generator._process_file_mode_tool([{"input": "data"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert "Tool execution failed" in results[0].error


class TestFileModeLiineageChaining:
    """Test lineage chaining in FILE mode."""

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_lineage_chains_from_parent(self, mock_run):
        """FILE mode chains lineage from parent records."""
        # Tool preserves source_guid in output
        mock_run.return_value = (
            [
                {"source_guid": "parent-1", "question": "q1"},
                {"source_guid": "parent-1", "question": "q2"},
            ],
            True,
        )

        config = GeneratorConfig(
            agent_config={
                "granularity": "file",
                "model_vendor": "tool",
            },
            agent_name="flatten_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        mock_processor = MagicMock()

        # Real enrichment pipeline to test lineage
        from agent_actions.core.enrichment import EnrichmentPipeline

        mock_processor.enrichment_pipeline = EnrichmentPipeline()
        processor_factory.create_processor.return_value = mock_processor

        generator = TargetGenerator(config, processor_factory)
        generator.record_processor = mock_processor

        # Input with parent lineage (simulating previous stage output)
        input_data = [
            {
                "source_guid": "parent-1",
                "target_id": "target-abc",
                "node_id": "extract_qa_123",
                "lineage": ["extract_qa_123"],
                "content": {"questions": ["q1", "q2"]},
            }
        ]

        context = ProcessingContext(
            agent_config=config.agent_config,
            agent_name="flatten_tool",
            mode=ProcessingMode.ONLINE,
            is_first_stage=False,  # Not first stage - should chain lineage
            source_data=input_data,  # Parent data for lookup
        )

        results = generator._process_file_mode_tool(input_data, context)

        # Verify results
        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS

        # Each output should have chained lineage
        for item in results[0].data:
            assert "lineage" in item
            assert len(item["lineage"]) == 2  # Parent lineage + new node_id
            assert item["lineage"][0] == "extract_qa_123"  # Parent's node_id
            assert item["lineage"][1].startswith("flatten_tool_")  # New node_id

            # source_guid should be preserved at top level
            assert item.get("source_guid") == "parent-1"

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_first_stage_starts_fresh_lineage(self, mock_run):
        """First stage starts fresh lineage without chaining."""
        mock_run.return_value = ([{"data": "value"}], True)

        config = GeneratorConfig(
            agent_config={
                "granularity": "file",
                "model_vendor": "tool",
            },
            agent_name="first_tool",
            idx=0,
        )

        processor_factory = MagicMock()
        mock_processor = MagicMock()

        from agent_actions.core.enrichment import EnrichmentPipeline

        mock_processor.enrichment_pipeline = EnrichmentPipeline()
        processor_factory.create_processor.return_value = mock_processor

        generator = TargetGenerator(config, processor_factory)
        generator.record_processor = mock_processor

        context = ProcessingContext(
            agent_config=config.agent_config,
            agent_name="first_tool",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,  # First stage
        )

        results = generator._process_file_mode_tool([{"input": "raw"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS

        # First stage lineage only has current node_id
        for item in results[0].data:
            assert "lineage" in item
            assert len(item["lineage"]) == 1
            assert item["lineage"][0].startswith("first_tool_")
