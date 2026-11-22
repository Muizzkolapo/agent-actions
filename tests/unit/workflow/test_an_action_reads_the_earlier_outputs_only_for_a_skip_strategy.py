"""An action reads every earlier action's output only when a skip strategy will look at it.

Each action read every stored file of every action before it, on the event loop's
thread, and held them while it ran, though no skip strategy is registered to read
them. At a late step of a long workflow that was every record of every earlier action,
for each action of the step at once (#1865).
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


@pytest.fixture
def deps():
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.state_manager.get_status.return_value = ActionStatus.PENDING
    deps.state_manager.get_status_details.return_value = {}
    deps.state_manager.adopt_truncation_marker.return_value = False
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.batch_manager.check_batch_submission.return_value = None
    deps.skip_evaluator = SkipEvaluator()
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.output_manager.resolve_correlated_input.return_value = None
    runner = deps.action_runner = MagicMock()
    runner.staged_input_fingerprint.return_value = None
    runner.workflow_name = "wf"
    runner.retried_records = frozenset()
    runner.action_configs = {}
    runner.execution_order = ["extract", "summarise"]
    runner.get_action_folder.return_value = "/tmp/agent_io"
    runner.run_action.return_value = "/output"
    runner.storage_backend.get_failed_items.return_value = []
    runner.storage_backend.has_disposition.return_value = False
    runner.storage_backend.get_storage_stats.return_value = {"nodes": {}}
    return deps


def _run(executor: ActionExecutor, *, run_async: bool):
    kwargs = {"action_idx": 1, "action_config": {}, "is_last_action": True}
    if run_async:
        return asyncio.run(executor.execute_action_async("summarise", **kwargs))
    return executor.execute_action_sync("summarise", **kwargs)


@pytest.mark.parametrize("run_async", [False, True], ids=["sync", "async"])
def test_no_strategy_reads_no_earlier_output(deps, run_async):
    result = _run(ActionExecutor(deps), run_async=run_async)

    assert result.status == ActionStatus.COMPLETED
    deps.action_runner.run_action.assert_called_once()
    deps.output_manager.get_previous_outputs.assert_not_called()


@pytest.mark.parametrize("run_async", [False, True], ids=["sync", "async"])
def test_a_registered_strategy_reads_the_earlier_outputs_and_can_skip(deps, run_async):
    outputs = {"extract": [{"source_guid": "sg1"}]}
    deps.output_manager.get_previous_outputs.return_value = outputs
    strategy = MagicMock()
    strategy.should_skip.return_value = True
    deps.skip_evaluator.strategies = [strategy]

    result = _run(ActionExecutor(deps), run_async=run_async)

    deps.output_manager.get_previous_outputs.assert_called_once_with(1)
    strategy.should_skip.assert_called_once_with({}, outputs)
    deps.action_runner.run_action.assert_not_called()
    assert result.status == ActionStatus.COMPLETED
