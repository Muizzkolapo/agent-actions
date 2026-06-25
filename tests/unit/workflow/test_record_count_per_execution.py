"""Regression tests for cumulative-on-rerun record_count overcount.

Before this fix, `_count_output_records` queried the storage backend's
`get_storage_stats` after the run and reported the SUM of all rows under
that action_name.  On resume / re-run that wrote to NEW paths (a second
batch item, a timestamped shard, an additional file), the SUM grew while
the action only produced the delta.  Example: run 1 wrote 50 rows;
resume processed item_2.jsonl with 50 more rows; ActionCompleteEvent
shipped record_count=100 for an execution that produced 50.

The fix is a before/after snapshot taken inside the executor.  The
per-execution delta (after - before) replaces the cumulative SUM.
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


def _build_deps(stats_sequence):
    """Build executor deps with a backend whose get_storage_stats returns
    successive values from ``stats_sequence``.

    The first call simulates the pre-run snapshot; the second simulates
    the post-run snapshot.  Use a list of len 2 for a single execution.
    """
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.action_runner = MagicMock()
    deps.action_runner.workflow_name = "wf"
    deps.action_runner.get_action_folder.return_value = "/tmp/agent_io"
    deps.action_runner.execution_order = ["agent_a"]
    deps.action_runner.storage_backend.has_disposition.return_value = False
    deps.action_runner.storage_backend.get_failed_items.return_value = []
    deps.action_runner.storage_backend.get_storage_stats.side_effect = stats_sequence
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
        stats_before = {"nodes": {"agent_a": 50}}
        stats_after = {"nodes": {"agent_a": 80}}
        deps = _build_deps([stats_before, stats_after])
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
        deps = _build_deps([{"nodes": {}}, {"nodes": {"agent_a": 25}}])
        deps.action_runner.run_action.return_value = "/out"
        executor = ActionExecutor(deps)

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._execute_action_run(_run_params())

        assert result.metrics.record_count == 25

    def test_run_that_writes_nothing_reports_zero(self):
        # Snapshots unchanged across the run.
        deps = _build_deps([{"nodes": {"agent_a": 12}}, {"nodes": {"agent_a": 12}}])
        deps.action_runner.run_action.return_value = "/out"
        executor = ActionExecutor(deps)

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._execute_action_run(_run_params())

        assert result.metrics.record_count == 0

    def test_delta_is_clamped_at_zero_if_rows_disappear(self):
        # If post-snapshot < pre-snapshot (e.g. a cleanup ran concurrently),
        # report 0 rather than a negative count.  Records-written is a count,
        # not a signed delta.
        deps = _build_deps([{"nodes": {"agent_a": 40}}, {"nodes": {"agent_a": 10}}])
        deps.action_runner.run_action.return_value = "/out"
        executor = ActionExecutor(deps)

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            result = executor._execute_action_run(_run_params())

        assert result.metrics.record_count == 0


class TestBatchPathReportsPerExecutionDelta:
    """Batch path: _handle_batch_check snapshots before/after similarly."""

    def test_batch_completion_reports_only_records_this_run_wrote(self):
        # Prior batch shard left 100 rows; this batch completion wrote 40 more.
        deps = _build_deps([{"nodes": {"batch_a": 100}}, {"nodes": {"batch_a": 140}}])
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


class TestSnapshotFailureRaises:
    """Backend errors during the pre/post snapshot must surface, not return 0."""

    def test_pre_run_snapshot_error_raises_runtimeerror(self):
        deps = _build_deps([RuntimeError("db locked"), {"nodes": {}}])
        deps.action_runner.run_action.return_value = "/out"
        executor = ActionExecutor(deps)

        with pytest.raises(RuntimeError, match="get_storage_stats.* failed"):
            executor._execute_action_run(_run_params())

    def test_post_run_snapshot_error_raises_runtimeerror(self):
        # Pre-run succeeds; post-run fails — this must NOT be swallowed
        # as record_count=0.  A workflow whose telemetry storage is broken
        # should fail loudly.
        deps = _build_deps([{"nodes": {}}, RuntimeError("db corrupt")])
        deps.action_runner.run_action.return_value = "/out"
        executor = ActionExecutor(deps)

        with patch("agent_actions.workflow.executor.get_last_usage", return_value=None):
            with pytest.raises(RuntimeError, match="get_storage_stats.* failed"):
                executor._execute_action_run(_run_params())

    def test_missing_storage_backend_raises_runtimeerror(self):
        executor = object.__new__(ActionExecutor)
        deps = MagicMock()
        del deps.action_runner.storage_backend  # attribute genuinely absent
        executor.deps = deps
        with pytest.raises(RuntimeError, match="no storage backend"):
            executor._count_records_for_action("agent_a")

    def test_non_integer_record_count_raises_runtimeerror(self):
        executor = object.__new__(ActionExecutor)
        deps = MagicMock()
        deps.action_runner.storage_backend.get_storage_stats.return_value = {
            "nodes": {"agent_a": "not-a-number"}
        }
        executor.deps = deps
        with pytest.raises(RuntimeError, match="non-integer record_count"):
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
