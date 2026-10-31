"""A stale completion (marked completed, but with no output in storage) is reset and run again.

execute_level_async verifies every completed action in a level before it asks for
the pending ones, and the coordinator's sequential path does the same, so an
action whose output is gone (after a store clear or a backend swap) runs again
instead of being skipped and leaving its downstream actions with no input.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.config.types import RunMode
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(storage_has_data: bool) -> ActionExecutor:
    """Build an ActionExecutor whose storage backend returns data or not."""
    state_manager = MagicMock()
    action_runner = MagicMock()
    storage_backend = MagicMock()
    storage_backend.list_target_files.return_value = ["output.json"] if storage_has_data else []
    storage_backend.has_disposition.return_value = False
    action_runner.storage_backend = storage_backend
    # A completed action on a plain run. Left as mocks, the status reads as nothing
    # and `retried_records` as a repair in progress.
    state_manager.get_status.return_value = ActionStatus.COMPLETED
    action_runner.retried_records = frozenset()
    # No known config: these cases exercise the storage check in isolation.
    # The config-change check is covered in test_config_change_reruns_action.py.
    action_runner.action_configs = {}

    deps = ExecutorDependencies(
        action_runner=action_runner,
        state_manager=state_manager,
        skip_evaluator=MagicMock(),
        batch_manager=MagicMock(),
        output_manager=MagicMock(),
    )
    return ActionExecutor(deps=deps)


# ---------------------------------------------------------------------------
# ActionExecutor.verify_completion_status
# ---------------------------------------------------------------------------


class TestVerifyCompletionStatus:
    """Public wrapper around _verify_completion_status — used by execute_level_async."""

    def test_returns_true_when_storage_has_data(self):
        """Action with SQLite output is genuinely complete — skip it."""
        executor = _make_executor(storage_has_data=True)
        result = executor.verify_completion_status("write_description")
        assert result is True
        executor.deps.state_manager.update_status.assert_not_called()
        executor.deps.state_manager.reopen.assert_not_called()

    def test_returns_false_and_resets_to_pending_when_storage_empty(self):
        """Stale completion (no SQLite data) → reset to 'pending' for re-run."""
        executor = _make_executor(storage_has_data=False)
        result = executor.verify_completion_status("write_description")
        assert result is False
        executor.deps.state_manager.reopen.assert_called_once_with(["write_description"])

    def test_returns_true_when_storage_backend_raises(self):
        """A failed read is no evidence the output changed, so the status file stands.

        Run again, the action answers the records it failed, which no plain run of a
        completed action does, and what reads it never sees the rows that adds.
        """
        executor = _make_executor(storage_has_data=True)
        executor.deps.action_runner.storage_backend.list_target_files.side_effect = RuntimeError(
            "connection error"
        )
        result = executor.verify_completion_status("write_description")
        assert result is True
        executor.deps.state_manager.update_status.assert_not_called()
        executor.deps.state_manager.reopen.assert_not_called()

    def test_returns_true_when_no_storage_backend(self):
        """No backend configured → trust the status file."""
        executor = _make_executor(storage_has_data=False)
        executor.deps.action_runner.storage_backend = None
        result = executor.verify_completion_status("write_description")
        assert result is True
        executor.deps.state_manager.update_status.assert_not_called()


# ---------------------------------------------------------------------------
# execute_level_async — verification before get_pending_actions
# ---------------------------------------------------------------------------


class TestExecuteLevelAsyncVerification:
    """execute_level_async must verify completed actions before deciding to skip."""

    @pytest.mark.asyncio
    async def test_stale_completed_action_is_reset_and_re_run(self):
        """
        Regression: if write_description is 'completed' but has no
        SQLite output, execute_level_async must reset it to 'pending' and dispatch it
        rather than silently skipping the entire level.
        """
        from agent_actions.workflow.parallel.action_executor import (
            ActionLevelOrchestrator,
            LevelExecutionParams,
        )

        # State manager: write_description starts as "completed", transitions to "pending"
        status = {"write_description": "completed"}

        state_manager = MagicMock()
        state_manager.is_completed.side_effect = lambda name: status.get(name) == "completed"
        state_manager.get_pending_actions.side_effect = lambda actions: [
            a for a in actions if status.get(a) != "completed"
        ]
        state_manager.get_batch_submitted_actions.return_value = []
        state_manager.get_failed_actions.return_value = []

        # Action executor: verify_completion_status resets write_description to pending
        action_executor = MagicMock()

        def _verify(name):
            status[name] = "pending"  # simulate reset
            return False  # stale — must re-run

        action_executor.verify_completion_status.side_effect = _verify

        # Capture which actions were dispatched
        dispatched: list[str] = []

        async def _fake_execute(action_name, **_):
            dispatched.append(action_name)
            from agent_actions.workflow.executor import ActionExecutionResult, ExecutionMetrics

            return ActionExecutionResult(
                success=True, status=ActionStatus.COMPLETED, metrics=ExecutionMetrics()
            )

        action_executor.execute_action_async.side_effect = _fake_execute

        orchestrator = ActionLevelOrchestrator(
            execution_order=["write_description"],
            action_configs={"write_description": {"agent_type": "write_description"}},
        )

        params = LevelExecutionParams(
            level_idx=0,
            level_actions=["write_description"],
            action_indices={"write_description": 0},
            state_manager=state_manager,
            action_executor=action_executor,
            concurrency_limit=5,
            total_steps=1,
        )

        level_complete = await orchestrator.execute_level_async(params)

        assert level_complete is True
        # verify_completion_status must have been called for the completed action
        action_executor.verify_completion_status.assert_called_once_with("write_description")
        # After reset, the action must have been dispatched
        assert "write_description" in dispatched

    @pytest.mark.asyncio
    async def test_genuinely_complete_level_is_skipped(self):
        """Level where all actions are genuinely complete (with SQLite data) is skipped."""
        from agent_actions.workflow.parallel.action_executor import (
            ActionLevelOrchestrator,
            LevelExecutionParams,
        )

        state_manager = MagicMock()
        state_manager.is_completed.return_value = True
        state_manager.get_pending_actions.return_value = []  # still empty after verification
        state_manager.get_batch_submitted_actions.return_value = []
        state_manager.get_failed_actions.return_value = []

        action_executor = MagicMock()
        action_executor.verify_completion_status.return_value = True  # data present

        orchestrator = ActionLevelOrchestrator(
            execution_order=["write_description"],
            action_configs={"write_description": {"agent_type": "write_description"}},
        )

        params = LevelExecutionParams(
            level_idx=0,
            level_actions=["write_description"],
            action_indices={"write_description": 0},
            state_manager=state_manager,
            action_executor=action_executor,
            concurrency_limit=5,
            total_steps=1,
        )

        level_complete = await orchestrator.execute_level_async(params)

        assert level_complete is True
        # Verification ran, found data → nothing dispatched
        action_executor.verify_completion_status.assert_called_once_with("write_description")
        action_executor.execute_action_async.assert_not_called()


# ---------------------------------------------------------------------------
# execute_level_async — mixed completed/pending level
# ---------------------------------------------------------------------------


class TestExecuteLevelAsyncMixedLevel:
    """verify_completion_status is only called for actions that are 'completed',
    not for pending ones in the same level."""

    @pytest.mark.asyncio
    async def test_only_completed_actions_are_verified(self):
        from agent_actions.workflow.parallel.action_executor import (
            ActionLevelOrchestrator,
            LevelExecutionParams,
        )

        # action_a is completed with valid data; action_b is pending
        status = {"action_a": "completed", "action_b": "pending"}

        state_manager = MagicMock()
        state_manager.is_completed.side_effect = lambda name: status.get(name) == "completed"
        state_manager.get_pending_actions.side_effect = lambda actions: [
            a for a in actions if status.get(a) != "completed"
        ]
        state_manager.get_batch_submitted_actions.return_value = []
        state_manager.get_failed_actions.return_value = []

        action_executor = MagicMock()
        # action_a has valid storage data — skip it
        action_executor.verify_completion_status.return_value = True

        dispatched: list[str] = []

        async def _fake_execute(action_name, **_):
            dispatched.append(action_name)
            from agent_actions.workflow.executor import ActionExecutionResult, ExecutionMetrics

            return ActionExecutionResult(
                success=True, status=ActionStatus.COMPLETED, metrics=ExecutionMetrics()
            )

        action_executor.execute_action_async.side_effect = _fake_execute

        orchestrator = ActionLevelOrchestrator(
            execution_order=["action_a", "action_b"],
            action_configs={
                "action_a": {"agent_type": "action_a"},
                "action_b": {"agent_type": "action_b"},
            },
        )

        params = LevelExecutionParams(
            level_idx=0,
            level_actions=["action_a", "action_b"],
            action_indices={"action_a": 0, "action_b": 1},
            state_manager=state_manager,
            action_executor=action_executor,
            concurrency_limit=5,
            total_steps=1,
        )

        level_complete = await orchestrator.execute_level_async(params)

        assert level_complete is True
        # verify_completion_status called only for the completed action
        action_executor.verify_completion_status.assert_called_once_with("action_a")
        # Only the pending action was dispatched
        assert dispatched == ["action_b"]


# ---------------------------------------------------------------------------
# coordinator._run_single_action — sequential verification path
# ---------------------------------------------------------------------------


class TestCoordinatorSequentialVerification:
    """_run_single_action must verify completed actions before skipping."""

    def _make_coordinator_mock(self, storage_has_data: bool):
        """Build a minimal AgentWorkflow-shaped mock for _run_single_action."""
        mock = MagicMock()
        mock.action_configs = {"write_description": {"agent_type": "write_description"}}
        mock.execution_order = ["write_description"]
        mock.services.core.state_manager.is_completed.return_value = True
        mock.services.core.action_executor.verify_completion_status.return_value = storage_has_data
        return mock

    def test_genuinely_complete_action_is_skipped(self):
        """Sequential coordinator skips action when storage has valid data."""
        from agent_actions.workflow.coordinator import AgentWorkflow

        mock = self._make_coordinator_mock(storage_has_data=True)
        result = AgentWorkflow._run_single_action(
            mock, idx=0, action_name="write_description", total_actions=1
        )

        assert result is False
        mock.services.core.action_executor.execute_action_sync.assert_not_called()
        mock.event_logger.log_action_skip.assert_called_once_with(
            0, "write_description", 1, RunMode.ONLINE
        )

    def test_stale_completed_action_is_re_run(self):
        """Sequential coordinator re-runs action when storage has no data."""
        from agent_actions.workflow.coordinator import AgentWorkflow
        from agent_actions.workflow.executor import ActionExecutionResult, ExecutionMetrics

        mock = self._make_coordinator_mock(storage_has_data=False)
        mock.services.core.action_executor.execute_action_sync.return_value = ActionExecutionResult(
            success=True, status=ActionStatus.COMPLETED, metrics=ExecutionMetrics()
        )

        result = AgentWorkflow._run_single_action(
            mock, idx=0, action_name="write_description", total_actions=1
        )

        assert result is False
        mock.services.core.action_executor.execute_action_sync.assert_called_once_with(
            "write_description",
            action_idx=0,
            action_config={"agent_type": "write_description"},
            is_last_action=True,
        )
        mock.event_logger.log_action_skip.assert_not_called()
