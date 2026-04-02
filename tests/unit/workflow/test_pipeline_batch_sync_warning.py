"""Tests that batch + synchronous action emits a runtime warning."""

from unittest.mock import MagicMock, patch

from agent_actions.config.types import RunMode
from agent_actions.workflow.pipeline import FilePathsConfig, ProcessingPipeline, ProcessParams


def _make_process_params(kind: str, run_mode: RunMode = RunMode.BATCH) -> ProcessParams:
    """Create ProcessParams for pipeline tests."""
    return ProcessParams(
        action_config={"run_mode": run_mode, "kind": kind},
        action_name=f"test_{kind}_action",
        paths=FilePathsConfig(
            file_path="/tmp/input.json",
            base_directory="/tmp",
            output_directory="/tmp/output",
        ),
        idx=0,
        processor_factory=MagicMock(),
    )


class TestBatchSyncWarning:
    """Verify runtime warning when batch mode meets synchronous action kind."""

    @patch("agent_actions.workflow.pipeline.create_processing_pipeline_from_params")
    @patch("agent_actions.workflow.pipeline.logger")
    def test_batch_tool_logs_warning(self, mock_logger, mock_create):
        """Batch + kind=tool should log a warning and proceed in online mode."""
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = "/tmp/output/input.json"
        mock_create.return_value = mock_pipeline

        params = _make_process_params("tool")
        ProcessingPipeline.process_file(params)

        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0] % mock_logger.warning.call_args[0][1:]
        assert "run_mode=batch" in warning_msg
        assert "tool" in warning_msg
        mock_pipeline.process.assert_called_once()

    @patch("agent_actions.workflow.pipeline.create_processing_pipeline_from_params")
    @patch("agent_actions.workflow.pipeline.logger")
    def test_batch_hitl_logs_warning(self, mock_logger, mock_create):
        """Batch + kind=hitl should log a warning and proceed in online mode."""
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = "/tmp/output/input.json"
        mock_create.return_value = mock_pipeline

        params = _make_process_params("hitl")
        ProcessingPipeline.process_file(params)

        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0] % mock_logger.warning.call_args[0][1:]
        assert "run_mode=batch" in warning_msg
        assert "hitl" in warning_msg
        mock_pipeline.process.assert_called_once()

    @patch("agent_actions.workflow.pipeline.create_processing_pipeline_from_params")
    @patch("agent_actions.workflow.pipeline.logger")
    def test_online_tool_no_warning(self, mock_logger, mock_create):
        """Online + kind=tool should NOT log a warning."""
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = "/tmp/output/input.json"
        mock_create.return_value = mock_pipeline

        params = _make_process_params("tool", RunMode.ONLINE)
        ProcessingPipeline.process_file(params)

        mock_logger.warning.assert_not_called()
