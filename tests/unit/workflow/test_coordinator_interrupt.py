"""Interrupted workflows must record terminal state without losing resume progress."""

import asyncio
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.storage.backend import RUNNING_CLEAR_DISPOSITIONS
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.execution_events import WorkflowEventLogger
from agent_actions.workflow.managers.manifest import ManifestManager
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

    The event logger is real because the terminal-status sweep lives inside it;
    a mock would assert nothing about what actually reaches disk.
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
    wf.storage_backend = MagicMock()

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


def _patched_manager():
    mgr = MagicMock()
    mgr.context.return_value.__enter__ = MagicMock()
    mgr.context.return_value.__exit__ = MagicMock(return_value=False)
    return mgr


def _drive_until(wf, interrupt):
    """Run the sequential loop with the in-flight action raising `interrupt`."""
    with patch("agent_actions.workflow.coordinator.get_manager", return_value=_patched_manager()):
        with patch.object(AgentWorkflow, "_run_single_action", side_effect=interrupt):
            wf._run_workflow_with_context(datetime.now())


def _drive_async_until(wf, interrupt):
    """Run the async loop with level execution raising `interrupt`."""
    wf.services.core.action_level_orchestrator.execute_level_async = MagicMock(
        side_effect=interrupt
    )
    with patch("agent_actions.workflow.coordinator.get_manager", return_value=_patched_manager()):
        with patch.object(AgentWorkflow, "_initialize_event_context"):
            with patch.object(AgentWorkflow, "_persist_execution_metadata"):
                asyncio.run(wf.async_run())


class TestInterruptedRunRecordsTerminalStatus:
    """A run killed mid-action must not leave 'running' on disk forever."""

    def test_keyboard_interrupt_marks_running_action_interrupted(self, tmp_path):
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        assert _persisted_status(status_file, "agent_a") == ActionStatus.INTERRUPTED

    def test_system_exit_marks_running_action_interrupted(self, tmp_path):
        """SIGINT/SIGTERM reach the coordinator as SystemExit via the CLI handler."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(SystemExit):
            _drive_until(wf, SystemExit(130))

        assert _persisted_status(status_file, "agent_a") == ActionStatus.INTERRUPTED

    def test_async_cancellation_marks_running_action_interrupted(self, tmp_path):
        """The async loop needs its own handler; the sequential one cannot cover it."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(asyncio.CancelledError):
            _drive_async_until(wf, asyncio.CancelledError())

        assert _persisted_status(status_file, "agent_a") == ActionStatus.INTERRUPTED

    def test_interrupt_marks_workflow_failed_in_manifest(self, tmp_path):
        state_manager, _ = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        wf.services.support.manifest_manager.mark_workflow_failed.assert_called_once()

    def test_status_sweep_lands_even_if_manifest_write_raises(self, tmp_path):
        """The status file is what readers consult per action; it must not be lost."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)
        wf.services.support.manifest_manager.mark_workflow_failed.side_effect = RuntimeError(
            "manifest not initialized"
        )

        with pytest.raises(RuntimeError):
            _drive_until(wf, KeyboardInterrupt())

        assert _persisted_status(status_file, "agent_a") == ActionStatus.INTERRUPTED

    def test_ordinary_exception_still_marks_running_action_failed(self, tmp_path):
        """A workflow error is a real failure, not an interruption — keep them distinct."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(RuntimeError):
            _drive_until(wf, RuntimeError("boom"))

        assert _persisted_status(status_file, "agent_a") == ActionStatus.FAILED

    def test_untouched_action_is_not_swept(self, tmp_path):
        """Only in-flight actions get swept; pending work stays pending."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        assert _persisted_status(status_file, "agent_b") == ActionStatus.PENDING

    def test_batch_submitted_action_survives_the_sweep(self, tmp_path):
        """Batch work continues in the provider queue after this process dies."""
        state_manager, status_file = _running_state_manager(tmp_path)
        state_manager.update_status("agent_b", ActionStatus.BATCH_SUBMITTED)
        wf = _build_workflow(state_manager)

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        assert _persisted_status(status_file, "agent_b") == ActionStatus.BATCH_SUBMITTED

    def test_interrupt_sweeps_the_manifest_action_status(self, tmp_path):
        """The manifest must not read workflow=failed while its action reads running."""
        state_manager, _ = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        manifest = ManifestManager(tmp_path)
        manifest.initialize_manifest(
            workflow_name="test_workflow",
            execution_order=EXECUTION_ORDER,
            levels=[["agent_a"], ["agent_b"]],
            action_configs={name: {} for name in EXECUTION_ORDER},
        )
        manifest.mark_action_started("agent_a")
        wf.services.support.manifest_manager = manifest

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        written = json.loads((tmp_path / "logs" / ".manifest.json").read_text())
        assert written["actions"]["agent_a"]["status"] == ActionStatus.INTERRUPTED
        assert written["actions"]["agent_b"]["status"] == ActionStatus.PENDING
        assert written["status"] == "failed"

    def test_status_survives_an_interrupt_raised_by_an_event_handler(self, tmp_path):
        """A second Ctrl-C often lands inside event dispatch, which does disk I/O."""
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with patch(
            "agent_actions.workflow.execution_events.fire_event",
            side_effect=KeyboardInterrupt(),
        ):
            with pytest.raises(KeyboardInterrupt):
                _drive_until(wf, KeyboardInterrupt())

        assert _persisted_status(status_file, "agent_a") == ActionStatus.INTERRUPTED


class TestInterruptedRunResumesFromCheckpoint:
    """Interrupting must not cost the work already checkpointed.

    Drives the real _reset_retryable_actions rather than reproducing its logic,
    so the coupling between the interrupt sweep and the resume branch is covered.
    """

    def _interrupt_then_resume(self, tmp_path):
        state_manager, status_file = _running_state_manager(tmp_path)
        wf = _build_workflow(state_manager)

        with pytest.raises(KeyboardInterrupt):
            _drive_until(wf, KeyboardInterrupt())

        wf.storage_backend = MagicMock()
        wf._reset_retryable_actions()
        return wf, status_file

    def test_interrupted_action_clears_only_failure_dispositions(self, tmp_path):
        wf, _ = self._interrupt_then_resume(tmp_path)

        cleared = wf.storage_backend.clear_disposition.call_args_list
        assert {call.args for call in cleared} == {
            ("agent_a", disposition) for disposition in RUNNING_CLEAR_DISPOSITIONS
        }

    def test_interrupted_action_is_never_bulk_wiped(self, tmp_path):
        """A one-arg clear_disposition deletes every row, checkpointed SUCCESS included."""
        wf, _ = self._interrupt_then_resume(tmp_path)

        bulk_wipes = [
            call
            for call in wf.storage_backend.clear_disposition.call_args_list
            if len(call.args) == 1
        ]
        assert bulk_wipes == []

    def test_resume_returns_interrupted_action_to_pending(self, tmp_path):
        _, status_file = self._interrupt_then_resume(tmp_path)

        assert _persisted_status(status_file, "agent_a") == ActionStatus.PENDING
