"""Interrupted workflows must still write a terminal status for running actions."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.execution_events import WorkflowEventLogger
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from agent_actions.workflow.models import (
    CoreServices,
    SupportServices,
    WorkflowRuntimeConfig,
    WorkflowServices,
    WorkflowState,
)

EXECUTION_ORDER = ["agent_a", "agent_b"]


def _build_workflow(state_manager):
    """Build an AgentWorkflow with a real state manager and real event logger.

    The event logger is real because the terminal-status sweep lives inside
    handle_workflow_error; a mock would assert nothing about persistence.
    """
    wf = object.__new__(AgentWorkflow)

    metadata = MagicMock()
    metadata.agent_name = "test_workflow"
    metadata.execution_order = EXECUTION_ORDER
    metadata.action_indices = {name: idx for idx, name in enumerate(EXECUTION_ORDER)}
    metadata.action_configs = {
        name: {"agent_type": name, "type": "llm"} for name in EXECUTION_ORDER
    }
    wf.metadata = metadata

    wf.config = MagicMock(spec=WorkflowRuntimeConfig)

    runtime = MagicMock()
    runtime.state = WorkflowState()
    runtime.console = MagicMock()
    wf.runtime = runtime

    core = MagicMock(spec=CoreServices)
    core.state_manager = state_manager
    core.action_executor = MagicMock()
    core.action_level_orchestrator = MagicMock()
    core.action_level_orchestrator.compute_execution_levels.return_value = [["agent_a"]]
    support = MagicMock(spec=SupportServices)
    support.manifest_manager = MagicMock()
    wf.services = WorkflowServices(core=core, support=support)

    wf.event_logger = WorkflowEventLogger(
        agent_name="test_workflow",
        execution_order=EXECUTION_ORDER,
        config=wf.config,
        services=wf.services,
    )
    return wf


def _running_state_manager(tmp_path):
    status_file = tmp_path / ".agent_status.json"
    manager = ActionStateManager(status_file, EXECUTION_ORDER)
    manager.update_status("agent_a", ActionStatus.RUNNING)
    return manager, status_file


def _persisted_status(status_file, action_name):
    return json.loads(status_file.read_text())[action_name]["status"]


def _drive_until(wf, interrupt):
    """Run the sequential loop with the in-flight action raising `interrupt`."""
    mgr = MagicMock()
    mgr.context.return_value.__enter__ = MagicMock()
    mgr.context.return_value.__exit__ = MagicMock(return_value=False)

    with patch("agent_actions.workflow.coordinator.get_manager", return_value=mgr):
        with patch.object(AgentWorkflow, "_run_single_action", side_effect=interrupt):
            wf._run_workflow_with_context(datetime.now())


class TestInterruptedRunWritesTerminalStatus:
    """A run killed mid-action must not leave 'running' on disk forever."""

    def test_keyboard_interrupt_marks_running_action_failed(self, tmp_path):
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        assert _persisted_status(status_file, "agent_a") == ActionStatus.FAILED

    def test_system_exit_marks_running_action_failed(self, tmp_path):
        """SIGINT/SIGTERM reach the coordinator as SystemExit via the CLI handler."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(SystemExit):
            _drive_until(wf, SystemExit(130))

        assert _persisted_status(status_file, "agent_a") == ActionStatus.FAILED

    def test_interrupt_marks_workflow_failed_in_manifest(self, tmp_path):
        state_manager, _ = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        wf.services.support.manifest_manager.mark_workflow_failed.assert_called_once()

    def test_ordinary_exception_still_marks_running_action_failed(self, tmp_path):
        """Regression guard: widening the handler must not break the Exception path."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(RuntimeError):
            _drive_until(wf, RuntimeError("boom"))

        assert _persisted_status(status_file, "agent_a") == ActionStatus.FAILED

    def test_untouched_action_is_not_marked_failed(self, tmp_path):
        """Only in-flight actions get swept; pending work stays pending."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        assert _persisted_status(status_file, "agent_b") == ActionStatus.PENDING
