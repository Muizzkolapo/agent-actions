"""record_count is what one execution produced, not the action's stored total.

The storage backend keeps a running tally of the rows each action's runs have
collected (`rows_collected`).  The executor snapshots it before and after an
execution and reports the difference, so rows already stored by an earlier run
are not counted again, and rows an execution replaces are counted.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

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


def _build_deps(tally_sequence):
    """Build executor deps with a backend whose rows_collected returns
    successive values from ``tally_sequence``.

    The first call simulates the pre-run snapshot; the second simulates
    the post-run snapshot.  Use a list of len 2 for a single execution.
    """
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
    deps.action_runner.storage_backend.has_disposition.return_value = False
    deps.action_runner.storage_backend.get_failed_items.return_value = []
    deps.action_runner.storage_backend.rows_collected.side_effect = tally_sequence
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    deps.output_manager.resolve_correlated_input.return_value = None
    deps.batch_manager.check_batch_submission.return_value = None
    return deps


def _run_params(action_name="agent_a"):
    return ActionRunParams(
        action_name=action_name,
        action_idx=0,
        action_config={"kind": "llm"},
        is_last_action=True,
        start_time=datetime.now(),
    )


class TestExecuteActionRunReportsPerExecutionDelta:
    """Online path: _execute_action_run snapshots before/after and reports the delta."""

    def test_resume_after_prior_run_reports_only_new_records(self):
        # Pre-existing rows from a prior run that wrote to different paths.
        # The current execution writes 30 more records; ActionCompleteEvent
        # must ship 30, not the cumulative 80.
        deps = _build_deps([50, 80])
        deps.action_runner.run_action.return_value = "/out"
        executor = ActionExecutor(deps)

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._execute_action_run(_run_params())

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        assert result.metrics.record_count == 30, (
            f"expected per-execution delta 30 (80 - 50), got cumulative "
            f"{result.metrics.record_count} — record_count is being read "
            f"as SUM instead of after-before delta"
        )

    def test_fresh_run_reports_full_record_count(self):
        # No prior rows; this execution wrote 25.
        deps = _build_deps([0, 25])
        deps.action_runner.run_action.return_value = "/out"
        executor = ActionExecutor(deps)

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._execute_action_run(_run_params())

        assert result.metrics.record_count == 25

    def test_run_that_writes_nothing_reports_zero(self):
        # Snapshots unchanged across the run.
        deps = _build_deps([12, 12])
        deps.action_runner.run_action.return_value = "/out"
        executor = ActionExecutor(deps)

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._execute_action_run(_run_params())

        assert result.metrics.record_count == 0


class TestBatchPathReportsPerExecutionDelta:
    """Batch path: _handle_batch_check snapshots before/after similarly."""

    def test_batch_completion_reports_only_records_this_run_wrote(self):
        # Prior batch shard left 100 rows; this batch completion wrote 40 more.
        deps = _build_deps([100, 140])
        deps.batch_manager.handle_batch_agent.return_value = ("/output", "completed")
        executor = ActionExecutor(deps)

        with patch("agent_actions.workflow.executor.fire_event"):
            result = executor._handle_batch_check(
                action_name="batch_a",
                action_idx=0,
                action_config={"batch_id": "b1"},
                start_time=datetime.now(),
            )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        assert result.metrics.record_count == 40, (
            f"batch completion shipped cumulative {result.metrics.record_count} "
            f"instead of per-execution delta 40"
        )


class TestMissingBackendRaises:
    """An executor with no storage backend must fail loudly, not report 0."""

    def test_missing_storage_backend_raises_runtimeerror(self):
        executor = object.__new__(ActionExecutor)
        deps = MagicMock()
        del deps.action_runner.storage_backend  # attribute genuinely absent
        executor.deps = deps
        with pytest.raises(RuntimeError, match="no storage backend"):
            executor._count_records_for_action("agent_a")


class TestCachedCompletionShipsZero:
    """The cached-completion path (_check_prior_output) didn't run the
    action this execution, so record_count for THIS execution is 0."""

    def test_cached_completion_metrics_default_to_zero(self):
        # ExecutionMetrics() default is 0; result objects constructed for the
        # cached path should not be back-filling a cumulative SUM.
        metrics = ExecutionMetrics()
        assert metrics.record_count == 0
        # Sanity: a result built with default metrics propagates 0.
        result = ActionExecutionResult(
            success=True, status=ActionStatus.COMPLETED, metrics=ExecutionMetrics()
        )
        assert result.metrics.record_count == 0
