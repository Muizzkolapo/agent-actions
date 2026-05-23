"""Tests for parallel action executor exception handling.

Verifies that when one or more parallel actions raise exceptions,
asyncio.gather(return_exceptions=True) captures them, other actions
complete normally, and errors are logged.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from agent_actions.workflow.parallel.action_executor import (
    ActionLevelOrchestrator,
    ParallelExecutionParams,
)


@dataclass
class FakeActionResult:
    success: bool
    output_folder: str | None = None
    error: Exception | None = None
    status: str = "completed"
    metrics: None = None


class TestParallelExceptionHandling:
    """Tests for _execute_parallel_actions exception handling."""

    def _make_orchestrator(self, actions: list[str]) -> ActionLevelOrchestrator:
        configs = {a: {"run_mode": "online"} for a in actions}
        return ActionLevelOrchestrator(
            execution_order=actions,
            action_configs=configs,
        )

    def _make_params(self, actions: list[str], executor: AsyncMock) -> ParallelExecutionParams:
        return ParallelExecutionParams(
            pending_actions=actions,
            action_indices={a: i for i, a in enumerate(actions)},
            action_executor=executor,
            concurrency_limit=5,
            level_idx=0,
        )

    @pytest.mark.asyncio
    @patch("agent_actions.workflow.parallel.action_executor.fire_event")
    async def test_one_of_three_raises_others_complete(self, mock_fire_event):
        """One action raises; all three are still attempted."""
        actions = ["action_a", "action_b", "action_c"]
        orchestrator = self._make_orchestrator(actions)

        executor = AsyncMock()

        async def side_effect(action, **kwargs):
            if action == "action_b":
                raise RuntimeError("action_b exploded")
            return FakeActionResult(success=True)

        executor.execute_action_async.side_effect = side_effect
        params = self._make_params(actions, executor)

        await orchestrator._execute_parallel_actions(params)

        assert executor.execute_action_async.call_count == 3

    @pytest.mark.asyncio
    @patch("agent_actions.workflow.parallel.action_executor.fire_event")
    async def test_all_actions_raise_all_captured(self, mock_fire_event):
        """All actions raise — all are captured, function returns normally."""
        actions = ["act_1", "act_2", "act_3"]
        orchestrator = self._make_orchestrator(actions)

        executor = AsyncMock()
        executor.execute_action_async.side_effect = RuntimeError("boom")
        params = self._make_params(actions, executor)

        await orchestrator._execute_parallel_actions(params)

        assert executor.execute_action_async.call_count == 3

    @pytest.mark.asyncio
    @patch("agent_actions.workflow.parallel.action_executor.fire_event")
    async def test_exception_and_failed_result_both_captured(self, mock_fire_event):
        """One raises, one returns failed result — both handled without raising."""
        actions = ["raises", "fails_gracefully"]
        orchestrator = self._make_orchestrator(actions)

        executor = AsyncMock()

        async def side_effect(action, **kwargs):
            if action == "raises":
                raise RuntimeError("crash")
            return FakeActionResult(success=False, error=ValueError("bad input"))

        executor.execute_action_async.side_effect = side_effect
        params = self._make_params(actions, executor)

        await orchestrator._execute_parallel_actions(params)

        assert executor.execute_action_async.call_count == 2

    @pytest.mark.asyncio
    @patch("agent_actions.workflow.parallel.action_executor.fire_event")
    async def test_exception_fires_action_failed_event(self, mock_fire_event):
        """Exception in execute_action_async fires ActionFailedEvent."""
        actions = ["failing_action"]
        orchestrator = self._make_orchestrator(actions)

        executor = AsyncMock()
        executor.execute_action_async.side_effect = RuntimeError("kaboom")
        params = self._make_params(actions, executor)

        await orchestrator._execute_parallel_actions(params)

        assert mock_fire_event.call_count >= 1
        event = mock_fire_event.call_args_list[0][0][0]
        assert event.action_name == "failing_action"
        assert "kaboom" in event.error_message

    @pytest.mark.asyncio
    @patch("agent_actions.workflow.parallel.action_executor.fire_event")
    async def test_successful_actions_return_normally(self, mock_fire_event):
        """All actions succeed — function returns normally."""
        actions = ["a", "b", "c"]
        orchestrator = self._make_orchestrator(actions)

        executor = AsyncMock()
        executor.execute_action_async.return_value = FakeActionResult(success=True)
        params = self._make_params(actions, executor)

        await orchestrator._execute_parallel_actions(params)

        assert executor.execute_action_async.call_count == 3
