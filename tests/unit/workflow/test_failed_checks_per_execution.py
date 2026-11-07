"""The records an execution shipped with a failing verdict reach the action and workflow lines.

The backend tally is taken as an execution starts, dropping what an earlier one left, and
again as it completes. The second reading goes on the action's metrics and into the run's
total, which the workflow line reports.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent_actions.logging.events import ActionCompleteEvent, WorkflowCompleteEvent
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


def _deps(failed_takes):
    """Executor deps whose backend answers successive failed-checks takes from *failed_takes*."""
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
    backend.rows_collected.side_effect = [10, 14, 14, 18]
    backend.take_guard_skips.return_value = 0
    backend.take_checks_failed.side_effect = failed_takes
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    deps.output_manager.resolve_correlated_input.return_value = None
    deps.batch_manager.check_batch_submission.return_value = None
    return deps


def _online(executor: ActionExecutor) -> ActionExecutionResult:
    params = ActionRunParams("agent_a", 0, {"kind": "llm"}, True, datetime.now())
    with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
        return executor._execute_action_run(params)


def test_an_online_execution_reports_only_the_failures_it_collected():
    # 5 left by an earlier execution in this process, 3 collected by this one.
    deps = _deps([5, 3])
    deps.action_runner.run_action.return_value = "/out"
    executor = ActionExecutor(deps)

    result = _online(executor)

    assert result.status == ActionStatus.COMPLETED
    assert result.metrics.checks_failed == 3
    assert executor.records_failed_checks == 3


def test_a_batch_collection_reports_only_the_failures_it_collected():
    deps = _deps([5, 4])
    deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")
    executor = ActionExecutor(deps)

    with patch("agent_actions.workflow.executor.fire_event"):
        result = executor._handle_batch_check(
            action_name="batch_a",
            action_idx=0,
            action_config={"batch_id": "b1"},
            start_time=datetime.now(),
        )

    assert result.status == ActionStatus.COMPLETED
    assert result.metrics.checks_failed == 4
    assert executor.records_failed_checks == 4


def test_the_run_total_adds_every_execution_and_ignores_what_starts_drop():
    deps = _deps([9, 3, 9, 4])
    deps.action_runner.run_action.return_value = "/out"
    executor = ActionExecutor(deps)

    _online(executor)
    _online(executor)

    assert executor.records_failed_checks == 7


def test_the_sequential_loop_passes_the_count_to_the_action_event():
    logger = WorkflowEventLogger("wf", ["agent_a"], MagicMock(), MagicMock())
    result = ActionExecutionResult(
        success=True,
        output_folder="/out",
        metrics=ExecutionMetrics(duration=0.1, record_count=4, checks_failed=3),
    )
    params = ActionLogParams(0, "agent_a", 1, result, datetime.now(), 0.1, "online", {})

    with patch("agent_actions.workflow.execution_events.fire_event") as fire:
        logger.log_action_result(params)

    (event,) = [
        c.args[0] for c in fire.call_args_list if isinstance(c.args[0], ActionCompleteEvent)
    ]
    assert event.data["checks_failed"] == 3


def test_the_workflow_event_carries_the_run_total():
    services = MagicMock()
    services.core.state_manager.get_summary.return_value = {"completed": 3}
    services.core.action_executor = SimpleNamespace(records_failed_checks=7)
    services.support.manifest_manager = None
    logger = WorkflowEventLogger("wf", ["a", "b", "c"], MagicMock(), services)

    with (
        patch.object(WorkflowEventLogger, "_final_actions_left_empty", return_value=[]),
        patch("agent_actions.workflow.execution_events.fire_event") as fire,
    ):
        logger.finalize_workflow(elapsed_time=0.1)

    (event,) = [
        c.args[0] for c in fire.call_args_list if isinstance(c.args[0], WorkflowCompleteEvent)
    ]
    assert (event.data["actions_completed"], event.data["records_failed_checks"]) == (3, 7)


def test_a_new_run_starts_its_total_at_zero():
    services = MagicMock()
    services.core.action_executor = SimpleNamespace(records_failed_checks=7)
    logger = WorkflowEventLogger("wf", ["a"], MagicMock(), services)

    with (
        patch("agent_actions.workflow.execution_events.fire_event"),
        patch("agent_actions.workflow.execution_events.get_manager"),
    ):
        logger.log_workflow_start(datetime.now())

    assert services.core.action_executor.records_failed_checks == 0
