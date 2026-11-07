"""An action's guard-skip count is what one execution collected, on every path out.

The backend tally lives as long as the process. The executor takes it as an execution
starts, which drops what an earlier one left, and again as it completes; the second
reading reaches ``ActionCompleteEvent`` from the sequential and the parallel loop alike.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from agent_actions.logging.events import ActionCompleteEvent
from agent_actions.workflow.execution_events import WorkflowEventLogger
from agent_actions.workflow.executor import (
    ActionExecutionResult,
    ActionExecutor,
    ActionRunParams,
    ExecutionMetrics,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from agent_actions.workflow.models import ActionLogParams


def _deps(takes):
    """Executor deps whose backend answers successive guard-skip takes from *takes*."""
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.action_runner = MagicMock()
    deps.action_runner.staged_input_fingerprint.return_value = None
    deps.action_runner.workflow_name = "wf"
    deps.action_runner.get_action_folder.return_value = "/tmp/agent_io"
    deps.action_runner.execution_order = ["agent_a"]
    backend = deps.action_runner.storage_backend
    backend.has_disposition.return_value = False
    backend.get_failed_items.return_value = []
    backend.rows_collected.side_effect = [10, 14]
    backend.take_guard_skips.side_effect = takes
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    deps.output_manager.resolve_correlated_input.return_value = None
    deps.batch_manager.check_batch_submission.return_value = None
    return deps


def test_an_online_execution_reports_only_the_skips_it_collected():
    # 5 left by an earlier execution in this process, 2 collected by this one.
    deps = _deps([5, 2])
    deps.action_runner.run_action.return_value = "/out"
    params = ActionRunParams("agent_a", 0, {"kind": "llm"}, True, datetime.now())

    with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
        result = ActionExecutor(deps)._execute_action_run(params)

    assert result.status == ActionStatus.COMPLETED
    assert (result.metrics.record_count, result.metrics.guard_skipped) == (4, 2)


def test_a_batch_collection_reports_only_the_skips_it_collected():
    deps = _deps([5, 3])
    deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")

    with patch("agent_actions.workflow.executor.fire_event"):
        result = ActionExecutor(deps)._handle_batch_check(
            action_name="batch_a",
            action_idx=0,
            action_config={"batch_id": "b1"},
            start_time=datetime.now(),
        )

    assert result.status == ActionStatus.COMPLETED
    assert (result.metrics.record_count, result.metrics.guard_skipped) == (4, 3)


def test_the_sequential_loop_passes_the_count_to_the_event():
    logger = WorkflowEventLogger("wf", ["agent_a"], MagicMock(), MagicMock())
    result = ActionExecutionResult(
        success=True,
        output_folder="/out",
        metrics=ExecutionMetrics(duration=0.1, record_count=4, guard_skipped=1),
    )
    params = ActionLogParams(0, "agent_a", 1, result, datetime.now(), 0.1, "online", {})

    with patch("agent_actions.workflow.execution_events.fire_event") as fire:
        logger.log_action_result(params)

    (event,) = [
        c.args[0] for c in fire.call_args_list if isinstance(c.args[0], ActionCompleteEvent)
    ]
    assert (event.data["record_count"], event.data["guard_skipped"]) == (4, 1)
