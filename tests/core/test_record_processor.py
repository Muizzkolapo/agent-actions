"""Tests for RecordProcessor."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.core.record_processor import RecordProcessor
from agent_actions.core.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
)


class TestRecordProcessorInitialization:
    """Test RecordProcessor initialization."""

    def test_creates_enrichment_pipeline(self):
        """RecordProcessor initializes with EnrichmentPipeline."""
        processor = RecordProcessor(agent_config={}, agent_name="test")

        assert processor.enrichment_pipeline is not None
        assert len(processor.enrichment_pipeline.enrichers) == 5


class TestInputNormalization:
    """Test _normalize_input method."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_first_stage_generates_source_guid(self, mock_gen):
        """First-stage: generates source_guid from item."""
        mock_gen.return_value = "guid-123"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        content, source_guid, snapshot = processor._normalize_input({"raw": "data"}, context)

        mock_gen.assert_called_once_with({"raw": "data"})
        assert source_guid == "guid-123"
        assert snapshot == {"raw": "data"}

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_first_stage_filters_chunk_info_metadata(self, mock_gen):
        """First-stage: filters chunk_info metadata keys."""
        mock_gen.return_value = "guid-123"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        item = {
            "chunk_info": {"page": 1},
            "target_id": "id-1",
            "record_index": 0,
            "chunk_index": 0,
            "content": "data",
        }

        content, source_guid, snapshot = processor._normalize_input(item, context)

        # chunk_info metadata keys should be filtered
        assert "target_id" not in snapshot
        assert "record_index" not in snapshot
        assert "chunk_index" not in snapshot
        assert "chunk_info" in snapshot
        assert "content" in snapshot

    def test_subsequent_stage_extracts_content_and_guid(self):
        """Subsequent-stage: extracts content and source_guid."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        item = {"content": {"key": "value"}, "source_guid": "guid-456"}

        content, source_guid, snapshot = processor._normalize_input(item, context)

        assert content == {"key": "value"}
        assert source_guid == "guid-456"
        assert snapshot is None

    def test_subsequent_stage_handles_flat_item(self):
        """Subsequent-stage: handles item without 'content' key."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        item = {"key": "value", "source_guid": "guid-789"}

        content, source_guid, snapshot = processor._normalize_input(item, context)

        assert content == {"key": "value", "source_guid": "guid-789"}
        assert source_guid == "guid-789"


class TestGuardEvaluation:
    """Test _evaluate_guard method."""

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_no_guard_returns_none(self, mock_eval):
        """No guard config → returns None (proceed)."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        result = processor._evaluate_guard({"key": "value"}, "guid-123", context)

        assert result is None
        mock_eval.assert_not_called()

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_guard_allows_execution(self, mock_eval):
        """Guard evaluates to True → returns None (proceed)."""
        mock_eval.return_value = (True, "skip")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={"guard": {"clause": "status == 'active'"}}, agent_name="test"
        )

        result = processor._evaluate_guard({"status": "active"}, "guid-123", context)

        assert result is None

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_guard_skip_behavior(self, mock_eval):
        """Guard blocks with 'skip' → returns SKIPPED result."""
        mock_eval.return_value = (False, "skip")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={"guard": {"clause": "status == 'active'", "behavior": "skip"}},
            agent_name="test",
        )

        result = processor._evaluate_guard({"status": "inactive"}, "guid-123", context)

        assert isinstance(result, ProcessingResult)
        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "guard_skip"

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_guard_filter_behavior(self, mock_eval):
        """Guard blocks with 'filter' → returns FILTERED result."""
        mock_eval.return_value = (False, "filter")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={"guard": {"clause": "status == 'active'", "behavior": "filter"}},
            agent_name="test",
        )

        result = processor._evaluate_guard({"status": "inactive"}, "guid-123", context)

        assert isinstance(result, ProcessingResult)
        assert result.status == ProcessingStatus.FILTERED


class TestLLMExecution:
    """Test _execute_llm method."""

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_executes_llm_successfully(self, mock_run):
        """LLM executes successfully → returns response."""
        mock_run.return_value = ({"generated": "data"}, True)

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        prep_result = MagicMock()
        prep_result.formatted_prompt = "test prompt"
        prep_result.passthrough_fields = {"field": "value"}

        response, executed, passthrough = processor._execute_llm(
            {"content": "test"}, prep_result, context
        )

        assert response == {"generated": "data"}
        assert executed is True
        assert passthrough == {"field": "value"}

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_handles_non_execution(self, mock_run):
        """LLM returns executed=False → returns None response."""
        mock_run.return_value = (None, False)

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        prep_result = MagicMock()
        prep_result.formatted_prompt = "test prompt"
        prep_result.passthrough_fields = {}

        response, executed, passthrough = processor._execute_llm(
            {"content": "test"}, prep_result, context
        )

        assert response is None
        assert executed is False


class TestResponseTransformation:
    """Test _transform_response method."""

    @patch("agent_actions.utilities.processor.processor_helpers.transform_with_passthrough")
    def test_transforms_response(self, mock_transform):
        """Transforms LLM response to output format."""
        mock_transform.return_value = [{"transformed": "data"}]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        result = processor._transform_response(
            {"raw": "response"},
            {"content": "input"},
            "guid-123",
            {"field": "value"},
            context,
        )

        assert result == [{"transformed": "data"}]
        mock_transform.assert_called_once_with(
            {"raw": "response"}, {"content": "input"}, "guid-123", {}
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


class TestEndToEndProcessing:
    """Test full process() flow."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    @patch("agent_actions.utilities.processor.processor_helpers.transform_with_passthrough")
    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_node_id")
    @patch("agent_actions.utilities.lineage.LineageBuilder.build_lineage")
    def test_successful_first_stage_processing(
        self,
        mock_lineage,
        mock_node_id,
        mock_transform,
        mock_run,
        mock_prep,
        mock_guard,
        mock_guid,
    ):
        """First-stage: full successful processing flow."""
        # Setup mocks
        mock_guid.return_value = "guid-123"
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"generated": "data"}, True)
        mock_transform.return_value = [{"key": "value"}]
        mock_node_id.return_value = "node-456"
        mock_lineage.return_value = ["node-456"]

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        result = processor.process({"raw": "data"}, context)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.source_guid == "guid-123"
        assert result.node_id == "node-456"
        assert result.source_snapshot == {"raw": "data"}
        assert len(result.data) == 1

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    def test_guard_filter_short_circuits(self, mock_guard):
        """Guard filter → returns FILTERED immediately."""
        mock_guard.return_value = (False, "filter")

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={"guard": {"clause": "False", "behavior": "filter"}},
            agent_name="test",
        )

        result = processor.process({"content": "data", "source_guid": "guid-123"}, context)

        assert result.status == ProcessingStatus.FILTERED

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_llm_non_execution_returns_filtered(self, mock_run, mock_prep, mock_guard):
        """LLM non-execution with None response → returns FILTERED."""
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = (None, False)

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        result = processor.process({"content": "data", "source_guid": "guid-123"}, context)

        assert result.status == ProcessingStatus.FILTERED

    @patch("agent_actions.utilities.processor.processor_helpers.evaluate_guard_condition")
    @patch(
        "agent_actions.prompt_generation.prompt_preparation_service.PromptPreparationService.prepare_prompt_with_context"
    )
    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_llm_non_execution_with_response_returns_skipped(self, mock_run, mock_prep, mock_guard):
        """LLM non-execution with response → returns SKIPPED."""
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"passthrough": "data"}, False)

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        result = processor.process({"content": "data", "source_guid": "guid-123"}, context)

        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "guard_skip"


class TestSourceContentLookup:
    """Test _get_source_content method."""

    def test_returns_none_when_no_source_data(self):
        """No source_data → returns None."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", source_data=[])

        result = processor._get_source_content("guid-123", context)

        assert result is None

    @patch(
        "agent_actions.preprocessing.transformation.data_transformer.DataTransformer.get_content_by_source_guid"
    )
    def test_looks_up_source_content_by_guid(self, mock_get):
        """Looks up source content by GUID."""
        mock_get.return_value = {"source": "content"}

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(
            agent_config={},
            agent_name="test",
            source_data=[{"source_guid": "guid-123", "content": {"source": "content"}}],
        )

        result = processor._get_source_content("guid-123", context)

        assert result == {"source": "content"}


class TestItemContextCreation:
    """Test _create_item_context method."""

    def test_creates_new_context_with_updated_index(self):
        """Creates new context with updated record_index."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        base_context = ProcessingContext(
            agent_config={"model": "gpt-4"},
            agent_name="test",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
            source_data=[{"data": 1}],
            file_path="/path/to/file",
            record_index=0,
        )

        new_context = processor._create_item_context(base_context, 5, {"item": "data"})

        assert new_context.record_index == 5
        assert new_context.agent_config == {"model": "gpt-4"}
        assert new_context.agent_name == "test"
        assert new_context.mode == ProcessingMode.ONLINE
        assert new_context.is_first_stage is True
        assert new_context.file_path == "/path/to/file"

    def test_preserves_all_context_fields(self):
        """New context preserves all fields from base context."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        base_context = ProcessingContext(
            agent_config={"model": "gpt-4"},
            agent_name="test",
            mode=ProcessingMode.BATCH,
            loop_context={"loop_id": "loop-123"},
            workflow_metadata={"workflow": "test"},
            output_directory="/output",
        )

        new_context = processor._create_item_context(base_context, 3, {"item": "data"})

        assert new_context.loop_context == {"loop_id": "loop-123"}
        assert new_context.workflow_metadata == {"workflow": "test"}
        assert new_context.output_directory == "/output"
        assert new_context.mode == ProcessingMode.BATCH
