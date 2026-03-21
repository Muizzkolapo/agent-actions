"""Wave 8 Group C regression tests — Workflow Pipeline P1 fixes."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.llm.batch.core.batch_models import SubmissionResult
from agent_actions.processing.types import ProcessingContext
from agent_actions.workflow.config_pipeline import discover_workflow_udfs
from agent_actions.workflow.models import WorkflowPaths, WorkflowRuntimeConfig
from agent_actions.workflow.pipeline import BatchPipelineParams, PipelineConfig, ProcessingPipeline
from agent_actions.workflow.pipeline_file_mode import process_file_mode_hitl

# ---------------------------------------------------------------------------
# C-1  ·  _handle_batch_generation — tombstone passthrough path exercises
#          the `result.passthrough is not None` guard on pipeline.py:197
# ---------------------------------------------------------------------------


class TestHandleBatchGenerationTombstone:
    """C-1 — tombstone passthrough is written and the output path is returned."""

    def test_tombstone_passthrough_writes_data_and_returns_path(self, tmp_path):
        """_handle_batch_generation must not crash on a tombstone SubmissionResult
        and must write the passthrough data via FileWriter."""
        tombstone_data = [{"id": "rec-1", "status": "tombstoned"}]
        submission_result = SubmissionResult(
            passthrough={"type": "tombstone", "data": tombstone_data}
        )

        base_dir = tmp_path / "base"
        base_dir.mkdir()
        batch_file = base_dir / "batch_0.json"
        batch_file.write_text("[]")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        params = BatchPipelineParams(
            pipeline_action_config={"kind": "llm"},
            pipeline_action_name="extract",
            batch_file_path=str(batch_file),
            batch_base_directory=str(base_dir),
            batch_output_directory=str(out_dir),
            data=[],  # skip file read
        )

        mock_writer = MagicMock()

        with (
            patch(
                "agent_actions.workflow.pipeline.BatchSubmissionService.submit_batch_job",
                return_value=submission_result,
            ),
            patch(
                "agent_actions.workflow.pipeline.FileWriter",
                return_value=mock_writer,
            ),
        ):
            result_path = ProcessingPipeline._handle_batch_generation(params)

        mock_writer.write_target.assert_called_once_with(tombstone_data)
        assert result_path == str(out_dir / "batch_0.json")

    def test_non_tombstone_passthrough_does_not_write(self, tmp_path):
        """A non-tombstone passthrough must not invoke the FileWriter."""
        submission_result = SubmissionResult(batch_id="batch-xyz")

        base_dir = tmp_path / "base"
        base_dir.mkdir()
        batch_file = base_dir / "batch_0.json"
        batch_file.write_text("[]")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        params = BatchPipelineParams(
            pipeline_action_config={"kind": "llm"},
            pipeline_action_name="extract",
            batch_file_path=str(batch_file),
            batch_base_directory=str(base_dir),
            batch_output_directory=str(out_dir),
            data=[],
        )

        with (
            patch(
                "agent_actions.workflow.pipeline.BatchSubmissionService.submit_batch_job",
                return_value=submission_result,
            ),
            patch("agent_actions.workflow.pipeline.FileWriter") as mock_writer_cls,
        ):
            ProcessingPipeline._handle_batch_generation(params)

        mock_writer_cls.assert_not_called()


# ---------------------------------------------------------------------------
# C-3  ·  process_file_mode_hitl wraps non-AgentActionsError with context
# ---------------------------------------------------------------------------


def _make_pipeline():
    return ProcessingPipeline(
        config=PipelineConfig(
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review",
            idx=0,
        ),
        processor_factory=object(),
    )


class TestHITLFileModePropagatesExceptions:
    """C-3 — non-AgentActionsError propagates bare (not swallowed or wrapped)."""

    def test_runtime_error_propagates_bare(self):
        pipeline = _make_pipeline()
        context = ProcessingContext(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review",
        )
        with (
            patch(
                "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
                side_effect=RuntimeError("infra failure"),
            ),
            pytest.raises(RuntimeError, match="infra failure"),
        ):
            process_file_mode_hitl(pipeline, [{"source_guid": "sg-1", "content": {}}], [], context)

    def test_non_agent_error_propagates_as_original_type(self):
        pipeline = _make_pipeline()
        context = ProcessingContext(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review",
        )
        original = ValueError("bad value")
        with (
            patch(
                "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
                side_effect=original,
            ),
            pytest.raises(ValueError) as exc_info,
        ):
            process_file_mode_hitl(pipeline, [{"source_guid": "sg-1", "content": {}}], [], context)

        assert exc_info.value is original

    def test_agent_actions_error_passes_through_unchanged(self):
        """AgentActionsError is NOT re-wrapped — it re-raises directly."""
        pipeline = _make_pipeline()
        context = ProcessingContext(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review",
        )
        original = AgentActionsError("original app error")
        with (
            patch(
                "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
                side_effect=original,
            ),
            pytest.raises(AgentActionsError) as exc_info,
        ):
            process_file_mode_hitl(pipeline, [{"source_guid": "sg-1", "content": {}}], [], context)

        assert exc_info.value is original


# ---------------------------------------------------------------------------
# C-4  ·  discover_workflow_udfs skips manager branch when config.manager is None
# ---------------------------------------------------------------------------


class TestDiscoverWorkflowUDFsManagerNone:
    """C-4 — no AttributeError when config.manager is None."""

    def test_manager_none_does_not_raise(self, tmp_path):
        config = WorkflowRuntimeConfig(
            paths=WorkflowPaths(
                constructor_path=str(tmp_path),
                user_code_path=None,
                default_path=str(tmp_path),
            ),
            use_tools=False,
            manager=None,
        )
        console = MagicMock()
        # Should not raise AttributeError
        discover_workflow_udfs(config, console)

    def test_user_code_path_takes_priority_over_manager(self, tmp_path):
        """When user_code_path is set, manager is not accessed at all."""
        config = WorkflowRuntimeConfig(
            paths=WorkflowPaths(
                constructor_path=str(tmp_path),
                user_code_path=str(tmp_path),
                default_path=str(tmp_path),
            ),
            use_tools=False,
            manager=None,
        )
        console = MagicMock()
        with patch("agent_actions.workflow.config_pipeline._discover_udfs_from_path", return_value=0):
            discover_workflow_udfs(config, console)  # no AttributeError
