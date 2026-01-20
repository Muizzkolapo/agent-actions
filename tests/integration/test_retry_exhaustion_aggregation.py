"""
Integration tests for retry exhaustion aggregation in online mode.

Tests verify that ProcessingPipeline and InitialStagePipeline correctly handle
EXHAUSTED ProcessingResult statuses based on the on_exhausted config.
"""

import pytest
from unittest.mock import MagicMock, patch, Mock
from pathlib import Path

from agent_actions.processing.types import (
    ProcessingResult,
    ProcessingStatus,
    ProcessingContext,
    ProcessingMode,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.errors import AgentActionsException
from agent_actions.workflow.pipeline import ProcessingPipeline, PipelineConfig
from agent_actions.config.di.container import ProcessorFactory


class TestProcessingPipelineExhaustedHandling:
    """Tests for ProcessingPipeline aggregation of EXHAUSTED results."""

    def _create_exhausted_result(
        self,
        source_guid: str = "guid-123",
        attempts: int = 3,
        reason: str = "timeout",
    ) -> ProcessingResult:
        """Helper to create an EXHAUSTED ProcessingResult."""
        recovery = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=attempts,
                failures=attempts,
                succeeded=False,
                reason=reason,
            )
        )
        return ProcessingResult(
            status=ProcessingStatus.EXHAUSTED,
            data=[],
            source_guid=source_guid,
            recovery_metadata=recovery,
            source_snapshot={"original": "data"},
            input_record={"lineage": ["prev_node"], "target_id": "target-1"},
        )

    def _create_success_result(
        self,
        source_guid: str = "guid-456",
        content: dict = None,
    ) -> ProcessingResult:
        """Helper to create a SUCCESS ProcessingResult."""
        content = content or {"field": "value"}
        return ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"source_guid": source_guid, "content": content, "lineage": ["node-1"]}],
            source_guid=source_guid,
        )

    @patch("agent_actions.orchestration.processing_pipeline.RecordProcessor")
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    @patch("agent_actions.orchestration.processing_pipeline.OutputHandler")
    def test_on_exhausted_raise_throws_exception(
        self, mock_output_handler, mock_file_reader, mock_record_processor
    ):
        """
        When on_exhausted='raise' and an EXHAUSTED result exists,
        AgentActionsException should be raised.
        """
        agent_config = {
            "name": "test_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {"type": "object", "properties": {"field": {"type": "string"}}},
            "retry": {
                "enabled": True,
                "max_attempts": 3,
                "on_exhausted": "raise",
            },
        }

        config = PipelineConfig(
            agent_config=agent_config,
            agent_name="test_action",
            idx=1,
        )
        mock_factory = MagicMock(spec=ProcessorFactory)
        generator = ProcessingPipeline(config, mock_factory)

        # Mock process_batch to return an EXHAUSTED result
        exhausted_result = self._create_exhausted_result()
        mock_record_processor.return_value.process_batch.return_value = [exhausted_result]

        # Mock file reader
        mock_file_reader.return_value.read_file.return_value = [{"text": "input"}]

        with pytest.raises(AgentActionsException) as exc_info:
            generator._process_by_strategy(
                data=[{"text": "input"}],
                file_path="/path/to/file.json",
                base_directory="/base",
                output_directory="/output",
            )

        # Verify exception details
        assert "Retry exhausted" in str(exc_info.value)
        assert "on_exhausted=raise" in str(exc_info.value)
        assert exc_info.value.context["on_exhausted"] == "raise"
        assert exc_info.value.context["exhausted_records"] == 1

    @patch("agent_actions.orchestration.processing_pipeline.RecordProcessor")
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    @patch("agent_actions.orchestration.processing_pipeline.OutputHandler")
    def test_on_exhausted_return_last_writes_exhausted_record(
        self, mock_output_handler, mock_file_reader, mock_record_processor
    ):
        """
        When on_exhausted='return_last' (default), EXHAUSTED results
        should be converted to records with empty content and written to output.
        """
        agent_config = {
            "name": "test_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "tags": {"type": "array"},
                },
            },
            "retry": {
                "enabled": True,
                "max_attempts": 3,
                "on_exhausted": "return_last",
            },
        }

        config = PipelineConfig(
            agent_config=agent_config,
            agent_name="test_action",
            idx=1,
        )
        mock_factory = MagicMock(spec=ProcessorFactory)
        generator = ProcessingPipeline(config, mock_factory)

        # Mock process_batch to return an EXHAUSTED result
        exhausted_result = self._create_exhausted_result()
        mock_record_processor.return_value.process_batch.return_value = [exhausted_result]

        # Mock file reader
        mock_file_reader.return_value.read_file.return_value = [{"text": "input"}]

        # Mock output handler to capture what gets written
        mock_handler_instance = MagicMock()
        mock_output_handler.return_value = mock_handler_instance
        generator.output_handler = mock_handler_instance

        generator._process_by_strategy(
            data=[{"text": "input"}],
            file_path="/path/to/file.json",
            base_directory="/base",
            output_directory="/output",
        )

        # Verify save_main_output was called
        mock_handler_instance.save_main_output.assert_called_once()
        call_args = mock_handler_instance.save_main_output.call_args

        # Get the output data
        output_data = call_args[0][0]

        # Verify exhausted record structure
        assert len(output_data) == 1
        exhausted_record = output_data[0]

        assert exhausted_record["source_guid"] == "guid-123"
        assert exhausted_record["metadata"]["retry_exhausted"] is True
        assert "_recovery" in exhausted_record
        assert exhausted_record["_recovery"]["retry"]["attempts"] == 3
        assert exhausted_record["_recovery"]["retry"]["succeeded"] is False

        # Verify empty content based on schema
        assert exhausted_record["content"]["summary"] is None
        assert exhausted_record["content"]["tags"] == []

    @patch("agent_actions.orchestration.processing_pipeline.RecordProcessor")
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    @patch("agent_actions.orchestration.processing_pipeline.OutputHandler")
    def test_mixed_results_success_and_exhausted(
        self, mock_output_handler, mock_file_reader, mock_record_processor
    ):
        """
        When processing returns mixed SUCCESS and EXHAUSTED results,
        both should be included in output (with on_exhausted='return_last').
        """
        agent_config = {
            "name": "test_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {
                "type": "object",
                "properties": {"result": {"type": "string"}},
            },
            "retry": {
                "enabled": True,
                "max_attempts": 3,
                "on_exhausted": "return_last",
            },
        }

        config = PipelineConfig(
            agent_config=agent_config,
            agent_name="test_action",
            idx=1,
        )
        mock_factory = MagicMock(spec=ProcessorFactory)
        generator = ProcessingPipeline(config, mock_factory)

        # Create mixed results
        success_result = self._create_success_result(
            source_guid="guid-success",
            content={"result": "processed successfully"},
        )
        exhausted_result = self._create_exhausted_result(source_guid="guid-exhausted")

        mock_record_processor.return_value.process_batch.return_value = [
            success_result,
            exhausted_result,
        ]

        mock_file_reader.return_value.read_file.return_value = [
            {"text": "input1"},
            {"text": "input2"},
        ]

        mock_handler_instance = MagicMock()
        mock_output_handler.return_value = mock_handler_instance
        generator.output_handler = mock_handler_instance

        generator._process_by_strategy(
            data=[{"text": "input1"}, {"text": "input2"}],
            file_path="/path/to/file.json",
            base_directory="/base",
            output_directory="/output",
        )

        # Verify save_main_output was called
        mock_handler_instance.save_main_output.assert_called_once()
        output_data = mock_handler_instance.save_main_output.call_args[0][0]

        # Should have 2 records: 1 success + 1 exhausted
        assert len(output_data) == 2

        # Find success and exhausted records
        success_records = [
            r for r in output_data if not r.get("metadata", {}).get("retry_exhausted")
        ]
        exhausted_records = [r for r in output_data if r.get("metadata", {}).get("retry_exhausted")]

        assert len(success_records) == 1
        assert len(exhausted_records) == 1

        # Verify success record
        assert success_records[0]["source_guid"] == "guid-success"
        assert success_records[0]["content"]["result"] == "processed successfully"

        # Verify exhausted record
        assert exhausted_records[0]["source_guid"] == "guid-exhausted"
        assert exhausted_records[0]["_recovery"]["retry"]["succeeded"] is False

    @patch("agent_actions.orchestration.processing_pipeline.RecordProcessor")
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    @patch("agent_actions.orchestration.processing_pipeline.OutputHandler")
    def test_on_exhausted_raise_with_mixed_results_still_raises(
        self, mock_output_handler, mock_file_reader, mock_record_processor
    ):
        """
        When on_exhausted='raise' and there are mixed results including EXHAUSTED,
        exception should be raised even if some records succeeded.
        """
        agent_config = {
            "name": "test_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {"type": "object", "properties": {"field": {"type": "string"}}},
            "retry": {
                "enabled": True,
                "max_attempts": 3,
                "on_exhausted": "raise",
            },
        }

        config = PipelineConfig(
            agent_config=agent_config,
            agent_name="test_action",
            idx=1,
        )
        mock_factory = MagicMock(spec=ProcessorFactory)
        generator = ProcessingPipeline(config, mock_factory)

        # Create mixed results: 2 success, 1 exhausted
        success1 = self._create_success_result(source_guid="guid-1")
        success2 = self._create_success_result(source_guid="guid-2")
        exhausted = self._create_exhausted_result(source_guid="guid-3")

        mock_record_processor.return_value.process_batch.return_value = [
            success1,
            success2,
            exhausted,
        ]

        mock_file_reader.return_value.read_file.return_value = [
            {"text": "input1"},
            {"text": "input2"},
            {"text": "input3"},
        ]

        with pytest.raises(AgentActionsException) as exc_info:
            generator._process_by_strategy(
                data=[{"text": "input1"}, {"text": "input2"}, {"text": "input3"}],
                file_path="/path/to/file.json",
                base_directory="/base",
                output_directory="/output",
            )

        # Should raise even though 2 records succeeded
        assert "Retry exhausted" in str(exc_info.value)
        assert exc_info.value.context["exhausted_records"] == 1

    @patch("agent_actions.orchestration.processing_pipeline.RecordProcessor")
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    @patch("agent_actions.orchestration.processing_pipeline.OutputHandler")
    def test_exhausted_record_preserves_lineage(
        self, mock_output_handler, mock_file_reader, mock_record_processor
    ):
        """
        Exhausted records should preserve lineage from input_record.
        """
        agent_config = {
            "name": "test_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {"type": "object", "properties": {"field": {"type": "string"}}},
            "retry": {"enabled": True, "max_attempts": 3},
        }

        config = PipelineConfig(
            agent_config=agent_config,
            agent_name="test_action",
            idx=1,
        )
        mock_factory = MagicMock(spec=ProcessorFactory)
        generator = ProcessingPipeline(config, mock_factory)

        # Create exhausted result with lineage in input_record
        exhausted_result = ProcessingResult(
            status=ProcessingStatus.EXHAUSTED,
            data=[],
            source_guid="guid-123",
            recovery_metadata=RecoveryMetadata(
                retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="timeout")
            ),
            input_record={
                "lineage": ["action_1_node", "action_2_node"],
                "target_id": "target-abc",
                "parent_target_id": "parent-xyz",
                "root_target_id": "root-123",
            },
        )

        mock_record_processor.return_value.process_batch.return_value = [exhausted_result]
        mock_file_reader.return_value.read_file.return_value = [{"text": "input"}]

        mock_handler_instance = MagicMock()
        mock_output_handler.return_value = mock_handler_instance
        generator.output_handler = mock_handler_instance

        generator._process_by_strategy(
            data=[{"text": "input"}],
            file_path="/path/to/file.json",
            base_directory="/base",
            output_directory="/output",
        )

        output_data = mock_handler_instance.save_main_output.call_args[0][0]
        exhausted_record = output_data[0]

        # Verify lineage is preserved and extended
        assert "action_1_node" in exhausted_record["lineage"]
        assert "action_2_node" in exhausted_record["lineage"]
        assert len(exhausted_record["lineage"]) == 3  # 2 prev + 1 new node_id

        # Verify target tracking fields
        assert exhausted_record["target_id"] == "target-abc"
        assert exhausted_record["parent_target_id"] == "parent-xyz"
        assert exhausted_record["root_target_id"] == "root-123"

    @patch("agent_actions.orchestration.processing_pipeline.RecordProcessor")
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    @patch("agent_actions.orchestration.processing_pipeline.OutputHandler")
    def test_default_on_exhausted_is_return_last(
        self, mock_output_handler, mock_file_reader, mock_record_processor
    ):
        """
        When on_exhausted is not specified, default behavior is 'return_last'
        (write exhausted record instead of raising).
        """
        agent_config = {
            "name": "test_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {"type": "object", "properties": {"field": {"type": "string"}}},
            "retry": {
                "enabled": True,
                "max_attempts": 3,
                # on_exhausted NOT specified - should default to return_last
            },
        }

        config = PipelineConfig(
            agent_config=agent_config,
            agent_name="test_action",
            idx=1,
        )
        mock_factory = MagicMock(spec=ProcessorFactory)
        generator = ProcessingPipeline(config, mock_factory)

        exhausted_result = self._create_exhausted_result()
        mock_record_processor.return_value.process_batch.return_value = [exhausted_result]
        mock_file_reader.return_value.read_file.return_value = [{"text": "input"}]

        mock_handler_instance = MagicMock()
        mock_output_handler.return_value = mock_handler_instance
        generator.output_handler = mock_handler_instance

        # Should NOT raise - should write exhausted record
        generator._process_by_strategy(
            data=[{"text": "input"}],
            file_path="/path/to/file.json",
            base_directory="/base",
            output_directory="/output",
        )

        # Verify record was written
        mock_handler_instance.save_main_output.assert_called_once()
        output_data = mock_handler_instance.save_main_output.call_args[0][0]
        assert len(output_data) == 1
        assert output_data[0]["metadata"]["retry_exhausted"] is True


class TestStagingLoaderExhaustedHandling:
    """Tests for StagingLoader aggregation of EXHAUSTED results (first-stage)."""

    def _create_exhausted_result(
        self,
        source_guid: str = "guid-first-stage",
        attempts: int = 3,
    ) -> ProcessingResult:
        """Helper to create an EXHAUSTED ProcessingResult for first-stage."""
        recovery = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=attempts,
                failures=attempts,
                succeeded=False,
                reason="timeout",
            )
        )
        return ProcessingResult(
            status=ProcessingStatus.EXHAUSTED,
            data=[],
            source_guid=source_guid,
            recovery_metadata=recovery,
            source_snapshot={"raw": "input data"},
        )

    def _create_success_result(self, source_guid: str = "guid-success") -> ProcessingResult:
        """Helper to create a SUCCESS ProcessingResult."""
        return ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"source_guid": source_guid, "content": {"extracted": "data"}}],
            source_guid=source_guid,
        )

    @patch("agent_actions.preprocessing.staging.initial_stage_pipeline.FileWriter")
    @patch("agent_actions.preprocessing.staging.initial_stage_pipeline.RecordProcessor")
    def test_first_stage_on_exhausted_raise(
        self, mock_record_processor, mock_file_writer, tmp_path
    ):
        """
        First-stage processing with on_exhausted='raise' should raise exception.
        """
        from agent_actions.input.preprocessing.staging.initial_stage_pipeline import (
            _process_realtime_mode_with_record_processor,
            InitialStageContext,
        )

        agent_config = {
            "name": "extract_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {"type": "object", "properties": {"text": {"type": "string"}}},
            "retry": {
                "enabled": True,
                "max_attempts": 3,
                "on_exhausted": "raise",
            },
        }

        # Create temp directories
        base_dir = tmp_path / "base"
        output_dir = tmp_path / "output"
        base_dir.mkdir()
        output_dir.mkdir()
        file_path = base_dir / "input.json"
        file_path.touch()

        ctx = InitialStageContext(
            agent_config=agent_config,
            agent_name="extract_action",
            file_path=str(file_path),
            base_directory=str(base_dir),
            output_directory=str(output_dir),
        )

        # Mock RecordProcessor to return EXHAUSTED
        exhausted_result = self._create_exhausted_result()
        mock_record_processor.return_value.process_batch.return_value = [exhausted_result]

        with pytest.raises(AgentActionsException) as exc_info:
            _process_realtime_mode_with_record_processor(
                data_chunk=[{"raw": "input"}],
                ctx=ctx,
                file_path=str(file_path),
                base_directory=str(base_dir),
                output_directory=str(output_dir),
            )

        assert "Retry exhausted" in str(exc_info.value)
        assert exc_info.value.context["on_exhausted"] == "raise"

    @patch("agent_actions.preprocessing.staging.initial_stage_pipeline.FileWriter")
    @patch("agent_actions.preprocessing.staging.initial_stage_pipeline.RecordProcessor")
    def test_first_stage_on_exhausted_return_last(
        self, mock_record_processor, mock_file_writer, tmp_path
    ):
        """
        First-stage processing with on_exhausted='return_last' should write exhausted record.
        """
        from agent_actions.input.preprocessing.staging.initial_stage_pipeline import (
            _process_realtime_mode_with_record_processor,
            InitialStageContext,
        )

        agent_config = {
            "name": "extract_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "items": {"type": "array"},
                },
            },
            "retry": {
                "enabled": True,
                "max_attempts": 3,
                "on_exhausted": "return_last",
            },
        }

        # Create temp directories
        base_dir = tmp_path / "base"
        output_dir = tmp_path / "output"
        base_dir.mkdir()
        output_dir.mkdir()
        file_path = base_dir / "input.json"
        file_path.touch()

        ctx = InitialStageContext(
            agent_config=agent_config,
            agent_name="extract_action",
            file_path=str(file_path),
            base_directory=str(base_dir),
            output_directory=str(output_dir),
        )

        exhausted_result = self._create_exhausted_result()
        mock_record_processor.return_value.process_batch.return_value = [exhausted_result]

        mock_file_writer_instance = MagicMock()
        mock_file_writer.return_value = mock_file_writer_instance

        _process_realtime_mode_with_record_processor(
            data_chunk=[{"raw": "input"}],
            ctx=ctx,
            file_path=str(file_path),
            base_directory=str(base_dir),
            output_directory=str(output_dir),
        )

        # Verify write_staging was called
        mock_file_writer_instance.write_staging.assert_called_once()
        written_data = mock_file_writer_instance.write_staging.call_args[0][0]

        # Verify exhausted record structure
        assert len(written_data) == 1
        record = written_data[0]
        assert record["metadata"]["retry_exhausted"] is True
        assert record["_recovery"]["retry"]["succeeded"] is False
        assert record["content"]["summary"] is None
        assert record["content"]["items"] == []

    @patch("agent_actions.preprocessing.staging.initial_stage_pipeline.FileWriter")
    @patch("agent_actions.preprocessing.staging.initial_stage_pipeline.RecordProcessor")
    def test_first_stage_mixed_results(self, mock_record_processor, mock_file_writer, tmp_path):
        """
        First-stage processing with mixed SUCCESS and EXHAUSTED should include both.
        """
        from agent_actions.input.preprocessing.staging.initial_stage_pipeline import (
            _process_realtime_mode_with_record_processor,
            InitialStageContext,
        )

        agent_config = {
            "name": "extract_action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {"type": "object", "properties": {"field": {"type": "string"}}},
            "retry": {"enabled": True, "max_attempts": 3},
        }

        # Create temp directories
        base_dir = tmp_path / "base"
        output_dir = tmp_path / "output"
        base_dir.mkdir()
        output_dir.mkdir()
        file_path = base_dir / "input.json"
        file_path.touch()

        ctx = InitialStageContext(
            agent_config=agent_config,
            agent_name="extract_action",
            file_path=str(file_path),
            base_directory=str(base_dir),
            output_directory=str(output_dir),
        )

        success_result = self._create_success_result()
        exhausted_result = self._create_exhausted_result()

        mock_record_processor.return_value.process_batch.return_value = [
            success_result,
            exhausted_result,
        ]

        mock_file_writer_instance = MagicMock()
        mock_file_writer.return_value = mock_file_writer_instance

        _process_realtime_mode_with_record_processor(
            data_chunk=[{"raw": "input1"}, {"raw": "input2"}],
            ctx=ctx,
            file_path=str(file_path),
            base_directory=str(base_dir),
            output_directory=str(output_dir),
        )

        written_data = mock_file_writer_instance.write_staging.call_args[0][0]

        # Should have 2 records
        assert len(written_data) == 2

        success_records = [
            r for r in written_data if not r.get("metadata", {}).get("retry_exhausted")
        ]
        exhausted_records = [
            r for r in written_data if r.get("metadata", {}).get("retry_exhausted")
        ]

        assert len(success_records) == 1
        assert len(exhausted_records) == 1
