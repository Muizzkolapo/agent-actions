"""Regression: ActionCompleteEvent must receive record_count from result — both serial and parallel modes.

Both call sites (parallel: ``ActionLevelOrchestrator._fire_action_result_event`` and
serial: ``WorkflowEventLogger.log_action_result``) historically omitted ``record_count``
from the ``ActionCompleteEvent(...)`` constructor, so the dataclass default of 0
silently shipped in every event. ``run_results.json`` and the docs-scanner
artefact audits then reported every successful action as having processed
0 records, regardless of actual output. These tests assert ``record_count``
survives end-to-end through both event paths.

The count is sourced from ``result.metrics.record_count`` (added to
``ExecutionMetrics`` in the same fix).
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from agent_actions.logging.events import ActionCompleteEvent
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
    """Defensive: a result whose metrics lacks record_count must surface 0, not crash.

    This guards the getattr fallback in the fix — RULES.md forbids silent
    fallbacks, but the dataclass default IS the explicit zero contract for the
    'no records produced' case (e.g. a guard-skipped or batch-submitted result).
    """
    from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

    orch = ActionLevelOrchestrator(execution_order=["agent_a"], action_configs={"agent_a": {}})
    result = MagicMock()
    result.success = True
    result.status = ActionStatus.COMPLETED
    # Real metrics object with no record_count attribute at all.
    result.metrics = MagicMock(spec=["tokens", "duration"])
    result.metrics.tokens = {}
    result.metrics.duration = 0.5
    result.output_folder = ""
    result.error = None

    with patch("agent_actions.workflow.parallel.action_executor.fire_event") as mock_fire:
        orch._fire_action_result_event("agent_a", idx=0, total=1, result=result, run_mode="online")

    complete = [
        c.args[0] for c in mock_fire.call_args_list if isinstance(c.args[0], ActionCompleteEvent)
    ]
    assert len(complete) == 1
    assert complete[0].record_count == 0
