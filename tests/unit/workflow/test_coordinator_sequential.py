"""Tests for AgentWorkflow sequential execution (_run_single_action, _run_workflow_with_context)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.executor import ActionExecutionResult, ExecutionMetrics
from agent_actions.workflow.managers.state import ActionStatus
from agent_actions.workflow.models import (
    CoreServices,
    SupportServices,
    WorkflowRuntimeConfig,
    WorkflowServices,
    WorkflowState,
)


def _build_workflow(execution_order=None, agent_configs=None, state=None):
    """Build an AgentWorkflow instance bypassing __init__.

    Uses object.__new__ to skip AgentWorkflow.__init__ which has 7+ side effects
    (config loading, storage init, dependency orchestration, etc.).  This lets us
    test _run_single_action / _run_workflow_with_context in isolation by injecting
    mock collaborators directly.
    """
    wf = object.__new__(AgentWorkflow)

    execution_order = execution_order or ["agent_a", "agent_b"]
    agent_configs = agent_configs or {
        name: {"agent_type": name, "type": "llm"} for name in execution_order
    }

    # Metadata (accessed via properties)
    metadata = MagicMock()
    metadata.agent_name = "test_workflow"
    metadata.execution_order = execution_order
    metadata.action_indices = {name: idx for idx, name in enumerate(execution_order)}
    metadata.action_configs = agent_configs
    wf.metadata = metadata

    # Config
    wf.config = MagicMock(spec=WorkflowRuntimeConfig)
    wf.config.run_downstream = False

    # Runtime state
    runtime = MagicMock()
    runtime.state = state or WorkflowState()
    runtime.console = MagicMock()
    wf.runtime = runtime

    # Services
    core = MagicMock(spec=CoreServices)
    core.state_manager = MagicMock()
    core.action_executor = MagicMock()
    support = MagicMock(spec=SupportServices)
    support.manifest_manager = MagicMock()
    wf.services = WorkflowServices(core=core, support=support)

    # Event logger
    wf.event_logger = MagicMock()

    return wf


def _success_result(status=ActionStatus.COMPLETED, output_folder="/output"):
    return ActionExecutionResult(
        success=True,
        status=status,
        output_folder=output_folder,
        metrics=ExecutionMetrics(duration=1.0),
    )


def _failed_result(error=None):
    return ActionExecutionResult(
        success=False,
        status=ActionStatus.FAILED,
        error=error or RuntimeError("agent failed"),
        metrics=ExecutionMetrics(duration=0.5),
    )


# ── _run_single_action ─────────────────────────────────────────────────


class TestRunSingleAgent:
    """Tests for _run_single_action sequential execution."""

    def test_already_completed_skips(self):
        """Completed agent should fire agent_start, then log skip, and not execute."""
        wf = _build_workflow()
        wf.services.core.state_manager.is_completed.return_value = True

        should_stop = wf._run_single_action(0, "agent_a", 2)

        assert should_stop is False
        # Source fires fire_action_start BEFORE the is_completed check (coordinator.py:296)
        wf.event_logger.fire_action_start.assert_called_once_with(
            0, "agent_a", 2, {"agent_type": "agent_a", "type": "llm"}
        )
        wf.event_logger.log_action_skip.assert_called_once_with(0, "agent_a", 2)
        wf.services.core.action_executor.execute_action_sync.assert_not_called()

    def test_success_appends_ephemeral(self):
        """Successful completion should append to ephemeral_directories."""
        wf = _build_workflow()
        wf.services.core.state_manager.is_completed.return_value = False
        wf.services.core.action_executor.execute_action_sync.return_value = _success_result()

        should_stop = wf._run_single_action(0, "agent_a", 2)

        assert should_stop is False
        assert len(wf.state.ephemeral_directories) == 1
        assert wf.state.ephemeral_directories[0]["output_folder"] == "/output"

    def test_batch_submitted_stops(self):
        """batch_submitted result should stop the workflow loop."""
        wf = _build_workflow()
        wf.services.core.state_manager.is_completed.return_value = False
        wf.services.core.action_executor.execute_action_sync.return_value = _success_result(
            status=ActionStatus.BATCH_SUBMITTED, output_folder=None
        )

        should_stop = wf._run_single_action(0, "agent_a", 2)

        assert should_stop is True

    def test_failure_continues(self):
        """Failed result should log and continue (circuit breaker handles downstream)."""
        wf = _build_workflow()
        wf.services.core.state_manager.is_completed.return_value = False
        error = RuntimeError("agent crashed")
        wf.services.core.action_executor.execute_action_sync.return_value = _failed_result(error)

        should_stop = wf._run_single_action(0, "agent_a", 2)
        assert should_stop is False

    def test_fires_agent_start(self):
        """Should fire agent_start event before execution."""
        wf = _build_workflow()
        wf.services.core.state_manager.is_completed.return_value = False
        wf.services.core.action_executor.execute_action_sync.return_value = _success_result()

        wf._run_single_action(0, "agent_a", 2)

        wf.event_logger.fire_action_start.assert_called_once()

    def test_is_last_action_flag(self):
        """is_last_action should be True for the final agent in execution_order."""
        wf = _build_workflow()
        wf.services.core.state_manager.is_completed.return_value = False
        wf.services.core.action_executor.execute_action_sync.return_value = _success_result()

        wf._run_single_action(1, "agent_b", 2)

        call_kwargs = wf.services.core.action_executor.execute_action_sync.call_args[1]
        assert call_kwargs["is_last_action"] is True


# ── _run_workflow_with_context ─────────────────────────────────────────


class TestRunWorkflowWithContext:
    """Tests for _run_workflow_with_context sequential loop."""

    def test_all_complete_returns_success_tuple(self):
        """When all agents complete, should return ('success', {})."""
        wf = _build_workflow()
        wf.services.core.state_manager.is_completed.return_value = True
        wf.services.core.state_manager.is_workflow_complete.return_value = True

        mgr = MagicMock()
        mgr.context.return_value.__enter__ = MagicMock()
        mgr.context.return_value.__exit__ = MagicMock(return_value=False)
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = wf._run_workflow_with_context(datetime.now())

        assert result == ("success", {})

    def test_batch_stops_early_returns_none(self):
        """When an agent returns batch_submitted, should stop and return None."""
        wf = _build_workflow(execution_order=["agent_a"])
        wf.services.core.state_manager.is_completed.return_value = False
        wf.services.core.action_executor.execute_action_sync.return_value = _success_result(
            status=ActionStatus.BATCH_SUBMITTED, output_folder=None
        )
        wf.services.core.state_manager.is_workflow_complete.return_value = False
        wf.services.core.state_manager.is_workflow_done.return_value = False

        mgr = MagicMock()
        mgr.context.return_value.__enter__ = MagicMock()
        mgr.context.return_value.__exit__ = MagicMock(return_value=False)
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = wf._run_workflow_with_context(datetime.now())

        assert result is None

    def test_failure_returns_completed_with_failures(self):
        """Failed action should produce completed_with_failures, not raise."""
        wf = _build_workflow(execution_order=["agent_a"])
        wf.services.core.state_manager.is_completed.return_value = False
        error = RuntimeError("boom")
        wf.services.core.action_executor.execute_action_sync.return_value = _failed_result(error)
        wf.services.core.state_manager.is_workflow_complete.return_value = False
        wf.services.core.state_manager.is_workflow_done.return_value = True
        wf.services.core.state_manager.get_failed_actions.return_value = ["agent_a"]

        mgr = MagicMock()
        mgr.context.return_value.__enter__ = MagicMock()
        mgr.context.return_value.__exit__ = MagicMock(return_value=False)
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = wf._run_workflow_with_context(datetime.now())

        assert result == ("completed_with_failures", {"failed": ["agent_a"]})
        assert wf.state.failed is True

    def test_unexpected_exception_calls_handle_workflow_error_and_reraises(self):
        """Unexpected crash (not a failed result) should call handle_workflow_error and re-raise."""
        wf = _build_workflow(execution_order=["agent_a"])
        wf.services.core.state_manager.is_completed.return_value = False
        wf.services.core.action_executor.execute_action_sync.side_effect = RuntimeError(
            "unexpected crash"
        )

        mgr = MagicMock()
        mgr.context.return_value.__enter__ = MagicMock()
        mgr.context.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr),
            pytest.raises(RuntimeError, match="unexpected crash"),
        ):
            wf._run_workflow_with_context(datetime.now())

        wf.event_logger.handle_workflow_error.assert_called_once()
        assert wf.state.failed is True

    def test_downstream_resolved_after_completion(self):
        """After all agents complete, should attempt downstream resolution."""
        wf = _build_workflow()
        wf.services.core.state_manager.is_completed.return_value = True
        wf.services.core.state_manager.is_workflow_complete.return_value = True
        wf._resolve_downstream_workflows = MagicMock(return_value=True)

        mgr = MagicMock()
        mgr.context.return_value.__enter__ = MagicMock()
        mgr.context.return_value.__exit__ = MagicMock(return_value=False)
        with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
            result = wf._run_workflow_with_context(datetime.now())

        assert result == ("success", {})
        wf._resolve_downstream_workflows.assert_called_once()
