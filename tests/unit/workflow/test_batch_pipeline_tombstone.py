"""Wave 8 Group C regression tests — Workflow Pipeline P1 fixes."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.llm.batch.core.batch_models import SubmissionResult
from agent_actions.processing.strategies.hitl import HITLStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.workflow.config_pipeline import discover_workflow_udfs
from agent_actions.workflow.models import WorkflowPaths, WorkflowRuntimeConfig
from agent_actions.workflow.pipeline import BatchPipelineParams, ProcessingPipeline

# ---------------------------------------------------------------------------
# C-1  ·  _handle_batch_generation — a run with nothing to send is written by
#          submission, so the caller writes nothing and returns its path
# ---------------------------------------------------------------------------


class TestHandleBatchGenerationNothingToSend:
    """C-1 — the caller leaves the write to submission, and returns the output path."""

    @staticmethod
    def _params(tmp_path):
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        batch_file = base_dir / "batch_0.json"
        batch_file.write_text("[]")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        backend = MagicMock()
        params = BatchPipelineParams(
            pipeline_action_config={"kind": "llm"},
            pipeline_action_name="extract",
            batch_file_path=str(batch_file),
            batch_base_directory=str(base_dir),
            batch_output_directory=str(out_dir),
            storage_backend=backend,
            data=[],  # skip file read
        )
        return params, backend, out_dir

    @pytest.mark.parametrize(
        "submitted",
        [SubmissionResult(passthrough={"type": "written"}), SubmissionResult(batch_id="b-1")],
        ids=["nothing_to_send", "sent"],
    )
    def test_the_caller_writes_nothing_and_returns_the_path(self, tmp_path, submitted):
        """Written here as well, the file would replace the one submission merged."""
        params, backend, out_dir = self._params(tmp_path)

        with patch(
            "agent_actions.workflow.pipeline.BatchSubmissionService.submit_batch_job",
            return_value=submitted,
        ):
            result_path = ProcessingPipeline._handle_batch_generation(params)

        backend.write_target.assert_not_called()
        backend.set_disposition.assert_not_called()
        assert result_path == str(out_dir / "batch_0.json")


# ---------------------------------------------------------------------------
# C-3  ·  HITLStrategy wraps non-AgentActionsError with context
# ---------------------------------------------------------------------------


class TestHITLFileModePropagatesExceptions:
    """C-3 — non-AgentActionsError propagates bare (not swallowed or wrapped)."""

    def test_runtime_error_propagates_bare(self):
        data = [{"source_guid": "sg-1", "content": {}}]
        context = ProcessingContext(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review",
        )
        context.source_data = data
        with (
            patch(
                "agent_actions.processing.strategies.hitl.run_dynamic_agent",
                side_effect=RuntimeError("infra failure"),
            ),
            pytest.raises(RuntimeError, match="infra failure"),
        ):
            HITLStrategy().invoke(data, context)

    def test_non_agent_error_propagates_as_original_type(self):
        data = [{"source_guid": "sg-1", "content": {}}]
        context = ProcessingContext(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review",
        )
        context.source_data = data
        original = ValueError("bad value")
        with (
            patch(
                "agent_actions.processing.strategies.hitl.run_dynamic_agent",
                side_effect=original,
            ),
            pytest.raises(ValueError) as exc_info,
        ):
            HITLStrategy().invoke(data, context)

        assert exc_info.value is original

    def test_agent_actions_error_passes_through_unchanged(self):
        """AgentActionsError is NOT re-wrapped — it re-raises directly."""
        data = [{"source_guid": "sg-1", "content": {}}]
        context = ProcessingContext(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review",
        )
        context.source_data = data
        original = AgentActionsError("original app error")
        with (
            patch(
                "agent_actions.processing.strategies.hitl.run_dynamic_agent",
                side_effect=original,
            ),
            pytest.raises(AgentActionsError) as exc_info,
        ):
            HITLStrategy().invoke(data, context)

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
        result = discover_workflow_udfs(config, console)
        assert result is None

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
        with patch(
            "agent_actions.workflow.config_pipeline._discover_udfs_from_path", return_value=0
        ):
            discover_workflow_udfs(config, console)  # no AttributeError
