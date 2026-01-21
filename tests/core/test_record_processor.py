"""Tests for RecordProcessor."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.types import (
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
        assert len(processor.enrichment_pipeline.enrichers) == 6


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
        """Subsequent-stage: extracts content, source_guid, and preserves input_record."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        item = {"content": {"key": "value"}, "source_guid": "guid-456"}

        content, source_guid, input_record = processor._normalize_input(item, context)

        assert content == {"key": "value"}
        assert source_guid == "guid-456"
        # Subsequent stages preserve the full input_record for lineage tracking
        assert input_record == item

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

        response, executed, passthrough, recovery_metadata = processor._execute_llm(
            {"content": "test"}, prep_result, context
        )

        assert response == {"generated": "data"}
        assert executed is True
        assert passthrough == {"field": "value"}
        assert recovery_metadata is None  # No retry occurred

    @patch("agent_actions.utilities.processor.processor_helpers.run_dynamic_agent")
    def test_handles_non_execution(self, mock_run):
        """LLM returns executed=False → returns None response."""
        mock_run.return_value = (None, False)

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test")

        prep_result = MagicMock()
        prep_result.formatted_prompt = "test prompt"
        prep_result.passthrough_fields = {}

        response, executed, passthrough, recovery_metadata = processor._execute_llm(
            {"content": "test"}, prep_result, context
        )

        assert response is None
        assert executed is False
        assert recovery_metadata is None


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


class TestNonDictInputValidation:
    """Test handling of non-dict inputs."""

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_first_stage_accepts_string_input(self, mock_guid):
        """First-stage accepts string input."""
        mock_guid.return_value = "guid-string"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        content, source_guid, snapshot = processor._normalize_input(
            "This is a plain string", context
        )

        assert content == "This is a plain string"
        assert source_guid == "guid-string"
        assert snapshot == "This is a plain string"

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_first_stage_accepts_list_input(self, mock_guid):
        """First-stage accepts list input."""
        mock_guid.return_value = "guid-list"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        content, source_guid, snapshot = processor._normalize_input([1, 2, 3], context)

        assert content == [1, 2, 3]
        assert source_guid == "guid-list"
        assert snapshot == [1, 2, 3]

    @patch("agent_actions.utilities.id_generation.IDGenerator.generate_deterministic_source_guid")
    def test_first_stage_accepts_none_input(self, mock_guid):
        """First-stage accepts None input."""
        mock_guid.return_value = "guid-none"

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        content, source_guid, snapshot = processor._normalize_input(None, context)

        assert content is None
        assert source_guid == "guid-none"
        assert snapshot is None

    def test_subsequent_stage_handles_non_dict_input(self):
        """Subsequent-stage handles non-dict input gracefully."""
        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=False)

        # Non-dict in subsequent-stage treated as raw content
        content, source_guid, snapshot = processor._normalize_input("unexpected string", context)

        assert content == "unexpected string"
        assert source_guid is None
        assert snapshot is None

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
    def test_end_to_end_with_string_input(
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
        """End-to-end processing with string input."""
        mock_guid.return_value = "guid-str"
        mock_node_id.return_value = "node-str"
        mock_lineage.return_value = ["node-str"]
        mock_guard.return_value = (True, "skip")
        mock_prep.return_value = MagicMock(formatted_prompt="prompt", passthrough_fields={})
        mock_run.return_value = ({"result": "processed"}, True)
        mock_transform.return_value = [{"content": "processed"}]
        mock_extract_meta.return_value = MagicMock(to_dict=lambda: {"tokens": 10})
        mock_loop_id.side_effect = lambda item, *args, **kwargs: {
            **item,
            "loop_id": "loop-123",
        }
        mock_field_mgr_inst = MagicMock()
        mock_field_mgr.return_value = mock_field_mgr_inst
        mock_field_mgr_inst.ensure_required_fields.side_effect = lambda item, *args: item

        processor = RecordProcessor(agent_config={}, agent_name="test")
        context = ProcessingContext(agent_config={}, agent_name="test", is_first_stage=True)

        result = processor.process("Plain text string", context)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.source_guid == "guid-str"
        assert result.source_snapshot == "Plain text string"


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
            mode=ProcessingMode.BATCH,
        )

        # ConfigurationError should be re-raised, not caught
        with pytest.raises(ConfigurationError) as exc_info:
            processor.process_batch([{"data": "test"}], context)

        assert "not in context_scope" in str(exc_info.value)

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
            mode=ProcessingMode.BATCH,
        )

        # Other exceptions should be caught and converted to failed results
        results = processor.process_batch([{"data": "test"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert "Some transient error" in results[0].error
