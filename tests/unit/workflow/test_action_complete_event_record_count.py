"""Regression: ActionCompleteEvent must receive record_count from result — both serial and parallel modes.

Both call sites (parallel: ``ActionLevelOrchestrator._fire_action_result_event`` and
serial: ``WorkflowEventLogger.log_action_result``) historically omitted ``record_count``
from the ``ActionCompleteEvent(...)`` constructor, so the dataclass default of 0
silently shipped in every event. ``run_results.json`` and the docs-scanner
artefact audits then reported every successful action as having processed
0 records, regardless of actual output. These tests assert ``record_count``
survives end-to-end through both event paths.

The count is sourced from ``result.metrics.record_count`` (added to
``ExecutionMetrics`` in the same fix). The producer-side helper
``ActionExecutor._count_output_records`` populates that field on the four
success construction sites: ``_handle_run_success`` (online + passthrough),
``_resolve_batch_outcome`` (batch completion), and ``_check_prior_output``
(cached completed result).
"""

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
    """Construct a fake ActionExecutionResult-shaped object with N output records."""
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
    # Serial path also reads tokens directly off result if present.
    result.tokens = result.metrics.tokens
    return result


def _make_executor_with_backend(stats_return=None, stats_side_effect=None, has_backend=True):
    """Build a minimal ActionExecutor with a mocked storage backend on action_runner.

    ``ActionExecutor.__init__`` only stores ``deps``, so we hand-construct a
    deps stub with the single attribute path ``_count_output_records`` touches:
    ``self.deps.action_runner.storage_backend.get_storage_stats``.
    """
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
        # Explicitly remove the attribute so getattr(..., None) returns None.
        del deps.action_runner.storage_backend
    executor.deps = deps
    return executor


def test_parallel_mode_fires_event_with_record_count():
    """Parallel: ActionCompleteEvent.record_count must equal result.metrics.record_count."""
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
    """Serial: WorkflowEventLogger.log_action_result must also populate record_count."""
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
    """Defensive: a result whose metrics is None must surface record_count=0, not crash.

    Producer-side population is the real contract — the call-site only protects
    against a result that has no metrics object at all (an unusual code path
    such as a stripped-down failure result reused for completion).
    """
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
    """Defensive: serial path mirror of the parallel test — metrics=None ships 0."""
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


# ----------------------------------------------------------------------------
# _count_output_records — producer-side helper tests
# ----------------------------------------------------------------------------


def test_count_output_records_happy_path_returns_node_count():
    """Backend returns {'nodes': {'agent_a': 5}} — helper returns 5."""
    executor = _make_executor_with_backend(stats_return={"nodes": {"agent_a": 5}})
    assert executor._count_output_records("agent_a") == 5


def test_count_output_records_no_storage_backend_returns_zero():
    """action_runner has no storage_backend attribute — helper returns 0 (no crash)."""
    executor = _make_executor_with_backend(has_backend=False)
    assert executor._count_output_records("agent_a") == 0


def test_count_output_records_backend_raises_logs_and_returns_zero(caplog):
    """get_storage_stats raises — helper logs warning and returns 0."""
    import logging

    executor = _make_executor_with_backend(stats_side_effect=RuntimeError("backend down"))
    target_logger = logging.getLogger("agent_actions.workflow.executor")
    # Some modules disable propagation; attach the caplog handler directly so the
    # warning is captured regardless of project-wide logging config.
    target_logger.addHandler(caplog.handler)
    target_logger.setLevel(logging.WARNING)
    try:
        result = executor._count_output_records("agent_a")
    finally:
        target_logger.removeHandler(caplog.handler)
    assert result == 0
    assert any("Could not read record_count for agent_a" in r.message for r in caplog.records), (
        f"expected warning log, got: {[r.message for r in caplog.records]}"
    )


def test_count_output_records_missing_nodes_key_returns_zero():
    """Backend returns empty dict (no 'nodes' key) — helper returns 0."""
    executor = _make_executor_with_backend(stats_return={})
    assert executor._count_output_records("agent_a") == 0


def test_count_output_records_none_value_for_action_returns_zero():
    """Backend returns {'nodes': {'agent_a': None}} — must not crash int(None).

    Proves the defensive ``or 0`` coercion in _count_output_records: a backend
    that records an explicit None for a node-level count must surface as 0
    rather than raising TypeError and breaking the action complete path.
    """
    executor = _make_executor_with_backend(stats_return={"nodes": {"agent_a": None}})
    assert executor._count_output_records("agent_a") == 0


# ----------------------------------------------------------------------------
# Batch path — _resolve_batch_outcome populates record_count
# ----------------------------------------------------------------------------


def test_resolve_batch_outcome_completed_populates_record_count():
    """Batch completion path: returned ActionExecutionResult.metrics.record_count is non-zero.

    Calls _resolve_batch_outcome directly with batch_status='completed' and a
    storage backend that reports 12 nodes for the action. Verifies the result
    threads through _count_output_records into ExecutionMetrics.record_count.
    """
    executor = _make_executor_with_backend(stats_return={"nodes": {"batch_action": 12}})
    # Stub the other collaborators _resolve_batch_outcome touches on the
    # completed branch: status resolution, state update, batch wall clock,
    # completion metadata. Each is independent of record_count.
    executor._compute_batch_wall_clock = MagicMock(return_value=3.0)
    executor._resolve_completion_status = MagicMock(return_value=ActionStatus.COMPLETED)
    executor._completion_metadata = MagicMock(return_value={})
    executor.deps.state_manager = MagicMock()

    with patch("agent_actions.workflow.executor.fire_event"):
        result = executor._resolve_batch_outcome(
            action_name="batch_action",
            action_config={"batch_id": "b1"},
            output_folder="/tmp/batch_action",
            batch_status="completed",
            duration=3.0,
        )

    assert isinstance(result, ActionExecutionResult)
    assert result.success is True
    assert result.status == ActionStatus.COMPLETED
    assert isinstance(result.metrics, ExecutionMetrics)
    assert result.metrics.record_count == 12, (
        f"batch completion did not thread record_count: got {result.metrics.record_count}, expected 12"
    )
