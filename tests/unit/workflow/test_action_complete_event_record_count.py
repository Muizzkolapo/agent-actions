"""ActionCompleteEvent must carry record_count from result.metrics in both serial and parallel modes."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from agent_actions.logging.events import ActionCompleteEvent
from agent_actions.workflow.executor import (
    ActionExecutionResult,
    ActionExecutor,
    ExecutionMetrics,
)
from agent_actions.workflow.managers.state import ActionStatus


def _build_successful_result(record_count: int):
    result = MagicMock()
    result.success = True
    result.status = ActionStatus.COMPLETED
    result.metrics = MagicMock(
        tokens={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        duration=1.5,
        record_count=record_count,
    )
    result.output_folder = "/tmp/agent_a"
    result.error = None
    result.tokens = result.metrics.tokens
    return result


def _make_executor_with_backend(stats_return=None, stats_side_effect=None, has_backend=True):
    executor = ActionExecutor.__new__(ActionExecutor)
    deps = MagicMock()
    if has_backend:
        backend = MagicMock()
        if stats_side_effect is not None:
            backend.get_storage_stats.side_effect = stats_side_effect
        else:
            backend.get_storage_stats.return_value = stats_return
        deps.action_runner.storage_backend = backend
    else:
        del deps.action_runner.storage_backend
    executor.deps = deps
    return executor


def test_parallel_mode_fires_event_with_record_count():
    from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

    orch = ActionLevelOrchestrator(execution_order=["agent_a"], action_configs={"agent_a": {}})
    result = _build_successful_result(record_count=7)

    with patch("agent_actions.workflow.parallel.action_executor.fire_event") as mock_fire:
        orch._fire_action_result_event("agent_a", idx=0, total=1, result=result, run_mode="online")

    events = [c.args[0] for c in mock_fire.call_args_list]
    complete = [e for e in events if isinstance(e, ActionCompleteEvent)]
    assert len(complete) == 1, f"expected 1 ActionCompleteEvent, got {len(complete)}"
    assert complete[0].record_count == 7, (
        f"parallel mode shipped record_count={complete[0].record_count}, expected 7"
    )


def test_serial_mode_fires_event_with_record_count():
    from agent_actions.workflow.execution_events import WorkflowEventLogger
    from agent_actions.workflow.models import (
        ActionLogParams,
        CoreServices,
        SupportServices,
        WorkflowRuntimeConfig,
        WorkflowServices,
    )

    core = MagicMock(spec=CoreServices)
    core.state_manager = MagicMock()
    support = MagicMock(spec=SupportServices)
    support.manifest_manager = MagicMock()
    services = WorkflowServices(core=core, support=support)
    config = MagicMock(spec=WorkflowRuntimeConfig)

    event_logger = WorkflowEventLogger(
        agent_name="test_workflow",
        execution_order=["agent_b"],
        config=config,
        services=services,
    )

    result = _build_successful_result(record_count=4)
    params = ActionLogParams(
        idx=0,
        action_name="agent_b",
        total_actions=1,
        result=result,
        end_time=datetime.now(),
        duration=1.5,
        run_mode="online",
    )

    with patch("agent_actions.workflow.execution_events.fire_event") as mock_fire:
        event_logger.log_action_result(params)

    events = [c.args[0] for c in mock_fire.call_args_list]
    complete = [e for e in events if isinstance(e, ActionCompleteEvent)]
    assert len(complete) == 1, f"expected 1 ActionCompleteEvent, got {len(complete)}"
    assert complete[0].record_count == 4, (
        f"serial mode shipped record_count={complete[0].record_count}, expected 4"
    )


def test_parallel_mode_missing_metrics_defaults_to_zero_explicitly():
    from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

    orch = ActionLevelOrchestrator(execution_order=["agent_a"], action_configs={"agent_a": {}})
    result = MagicMock()
    result.success = True
    result.status = ActionStatus.COMPLETED
    result.metrics = None
    result.output_folder = ""
    result.error = None

    with patch("agent_actions.workflow.parallel.action_executor.fire_event") as mock_fire:
        orch._fire_action_result_event("agent_a", idx=0, total=1, result=result, run_mode="online")

    complete = [
        c.args[0] for c in mock_fire.call_args_list if isinstance(c.args[0], ActionCompleteEvent)
    ]
    assert len(complete) == 1
    assert complete[0].record_count == 0


def test_serial_mode_missing_metrics_defaults_to_zero_explicitly():
    from agent_actions.workflow.execution_events import WorkflowEventLogger
    from agent_actions.workflow.models import (
        ActionLogParams,
        CoreServices,
        SupportServices,
        WorkflowRuntimeConfig,
        WorkflowServices,
    )

    core = MagicMock(spec=CoreServices)
    core.state_manager = MagicMock()
    support = MagicMock(spec=SupportServices)
    support.manifest_manager = MagicMock()
    services = WorkflowServices(core=core, support=support)
    config = MagicMock(spec=WorkflowRuntimeConfig)

    event_logger = WorkflowEventLogger(
        agent_name="test_workflow",
        execution_order=["agent_b"],
        config=config,
        services=services,
    )

    result = MagicMock()
    result.success = True
    result.status = ActionStatus.COMPLETED
    result.metrics = None
    result.output_folder = ""
    result.error = None
    result.tokens = None
    params = ActionLogParams(
        idx=0,
        action_name="agent_b",
        total_actions=1,
        result=result,
        end_time=datetime.now(),
        duration=0.5,
        run_mode="online",
    )

    with patch("agent_actions.workflow.execution_events.fire_event") as mock_fire:
        event_logger.log_action_result(params)

    complete = [
        c.args[0] for c in mock_fire.call_args_list if isinstance(c.args[0], ActionCompleteEvent)
    ]
    assert len(complete) == 1
    assert complete[0].record_count == 0


# Migration note: the silent-fallback `_count_output_records` helper was
# removed.  Its happy-path / missing-nodes-key behavior is now covered by
# `_count_records_for_action` (which raises on storage failure) in
# tests/unit/workflow/test_record_count_per_execution.py.  The synthetic
# "None value for action returns 0" test was deleted: get_storage_stats
# uses COALESCE(SUM(record_count), 0) and cannot produce None for an
# existing action, so the test exercised an unreachable code path.


def test_count_records_for_action_happy_path_returns_node_count():
    executor = _make_executor_with_backend(stats_return={"nodes": {"agent_a": 5}})
    assert executor._count_records_for_action("agent_a") == 5


def test_count_records_for_action_missing_nodes_key_returns_zero():
    # Empty stats payload means the action has no rows yet — that's a legitimate
    # 0, not a "we don't know" — so it does NOT raise.
    executor = _make_executor_with_backend(stats_return={})
    assert executor._count_records_for_action("agent_a") == 0


def test_resolve_batch_outcome_completed_populates_record_count():
    # After-run snapshot is 12, before-run snapshot was 0, so this execution
    # produced 12 records.  Passing pre_run_count=0 mirrors a fresh run.
    executor = _make_executor_with_backend(stats_return={"nodes": {"batch_action": 12}})
    executor._compute_batch_wall_clock = MagicMock(return_value=3.0)
    executor._resolve_completion_status = MagicMock(return_value=ActionStatus.COMPLETED)
    executor._completion_metadata = MagicMock(return_value={})
    executor.deps.state_manager = MagicMock()

    with patch("agent_actions.workflow.executor.fire_event"):
        result = executor._resolve_batch_outcome(
            action_name="batch_action",
            action_idx=0,
            action_config={"batch_id": "b1"},
            output_folder="/tmp/batch_action",
            batch_status="completed",
            duration=3.0,
            pre_run_count=0,
        )

    assert isinstance(result, ActionExecutionResult)
    assert result.success is True
    assert result.status == ActionStatus.COMPLETED
    assert isinstance(result.metrics, ExecutionMetrics)
    assert result.metrics.record_count == 12, (
        f"batch completion did not thread record_count: got {result.metrics.record_count}, expected 12"
    )
