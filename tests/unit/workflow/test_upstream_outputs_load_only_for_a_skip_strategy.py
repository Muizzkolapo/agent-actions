"""Upstream outputs are read for the skip check only when a strategy would read them."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

RAN = object()


@pytest.fixture
def deps():
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.state_manager.get_status.return_value = ActionStatus.PENDING
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.output_manager.get_previous_outputs.return_value = {"upstream": [{"x": 1}]}
    deps.action_runner = MagicMock()
    deps.action_runner.storage_backend = None
    deps.skip_evaluator = SkipEvaluator()
    return deps


def _execute(executor: ActionExecutor, mode: str):
    kwargs = {"action_idx": 1, "action_config": {"agent_type": "b"}, "is_last_action": False}
    with (
        patch.object(executor, "_check_upstream_health", return_value=None),
        patch.object(executor, "_execute_action_run", return_value=RAN),
        patch.object(executor, "_execute_action_run_async", AsyncMock(return_value=RAN)),
        patch.object(executor, "_handle_action_skip", return_value="skipped"),
    ):
        if mode == "sync":
            return executor.execute_action_sync("b", **kwargs)
        return asyncio.run(executor.execute_action_async("b", **kwargs))


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_with_no_strategy_upstream_outputs_are_not_loaded(deps, mode):
    assert _execute(ActionExecutor(deps), mode) is RAN
    deps.output_manager.get_previous_outputs.assert_not_called()


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_strategy_is_handed_the_upstream_outputs(deps, mode):
    strategy = MagicMock()
    strategy.should_skip.return_value = True
    deps.skip_evaluator.strategies = [strategy]

    assert _execute(ActionExecutor(deps), mode) == "skipped"
    deps.output_manager.get_previous_outputs.assert_called_once_with(1)
    strategy.should_skip.assert_called_once_with({"agent_type": "b"}, {"upstream": [{"x": 1}]})
