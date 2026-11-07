"""Records shipped with a failing verdict reach the action line and the workflow line.

The action line: the backend tally is taken as an execution starts, dropping what an
earlier one left, and again as it completes; the second reading goes on the metrics.
The workflow line: read from the store, so a batch workflow finishing over several runs
counts what the earlier runs collected.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from agent_actions.logging.events import ActionCompleteEvent, WorkflowCompleteEvent
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
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


def test_a_second_execution_reports_only_its_own_failures():
    deps = _deps([9, 3, 9, 4])
    deps.action_runner.run_action.return_value = "/out"
    executor = ActionExecutor(deps)

    first, second = _online(executor), _online(executor)

    assert (first.metrics.checks_failed, second.metrics.checks_failed) == (3, 4)


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


def _store_with(tmp_path, rows):
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="wf")
    backend.initialize()
    for action, record_id, disposition, reason in rows:
        backend.set_disposition(action, record_id, disposition, reason=reason)
    return backend


def _workflow_event(backend, order):
    services = MagicMock()
    services.core.state_manager.get_summary.return_value = {"completed": len(order)}
    services.core.action_executor.deps.action_runner.storage_backend = backend
    services.support.manifest_manager = None
    logger = WorkflowEventLogger("wf", order, MagicMock(), services)
    with (
        patch.object(WorkflowEventLogger, "_final_actions_left_empty", return_value=[]),
        patch("agent_actions.workflow.execution_events.fire_event") as fire,
    ):
        logger.finalize_workflow(elapsed_time=0.1)
    (event,) = [
        c.args[0] for c in fire.call_args_list if isinstance(c.args[0], WorkflowCompleteEvent)
    ]
    return event


def test_the_workflow_line_counts_the_failed_checks_the_store_holds(tmp_path):
    backend = _store_with(
        tmp_path,
        [
            ("a", "r1", "success", "expectations_failed"),
            ("a", "r2", "success", "expectations_failed"),
            ("a", "r3", "success", None),
            ("b", "r1", "success", "expectations_failed"),
            ("b", "r2", "failed", "expectations_failed"),
            ("b", "r3", "unprocessed", "guard_skip"),
            ("other", "r1", "success", "expectations_failed"),
        ],
    )

    event = _workflow_event(backend, ["a", "b"])

    assert (event.data["actions_completed"], event.data["records_failed_checks"]) == (2, 3)


def test_a_workflow_with_no_failed_checks_reports_none(tmp_path):
    backend = _store_with(tmp_path, [("a", "r1", "success", None)])

    assert _workflow_event(backend, ["a"]).data["records_failed_checks"] == 0


def test_failures_an_earlier_run_collected_still_count(tmp_path):
    # A batch workflow: "a" was collected by an earlier run; this run only finished "b".
    backend = _store_with(tmp_path, [("a", "r1", "success", "expectations_failed")])
    backend.set_disposition("b", "r1", "success")

    assert _workflow_event(backend, ["a", "b"]).data["records_failed_checks"] == 1
