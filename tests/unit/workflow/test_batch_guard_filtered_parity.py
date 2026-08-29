"""Guard-filtered-all must classify identically in batch and online mode.

An action whose every record is guard-filtered resolves as SKIPPED with
``skip_reason=GUARD_FILTERED_ALL``.  Online reaches that classification through
``_handle_run_success``.  Batch has two paths that reach completion without it:
``_resolve_batch_outcome`` (a finished batch) and the ``passthrough``
short-circuit in ``_handle_run_success``.  Both must agree with online.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.logging.events.workflow_events import ActionSkipEvent
from agent_actions.record.reasons import GUARD_FILTERED_ALL
from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "agent_a"
CONFIG = {"kind": "llm", "run_mode": "batch"}


@pytest.fixture
def deps():
    d = MagicMock(spec=ExecutorDependencies)
    d.state_manager = MagicMock(spec=ActionStateManager)
    d.batch_manager = MagicMock(spec=BatchLifecycleManager)
    d.action_runner = MagicMock()
    d.skip_evaluator = MagicMock(spec=SkipEvaluator)
    d.output_manager = MagicMock(spec=ActionOutputManager)
    d.action_runner.execution_order = [ACTION, "agent_b"]
    return d


@pytest.fixture
def executor(deps):
    return ActionExecutor(deps)


def _all_records_guard_filtered(deps, filtered: bool = True):
    """Node-level SKIPPED disposition is the guard-filtered-all signal."""
    deps.action_runner.storage_backend.has_disposition.return_value = filtered
    deps.action_runner.storage_backend.get_failed_items.return_value = []


def _params():
    return ActionRunParams(
        action_name=ACTION,
        action_idx=0,
        action_config=CONFIG,
        is_last_action=False,
        start_time=datetime.now(),
    )


def _skip_reason_of(deps):
    calls = deps.state_manager.update_status.call_args_list
    assert calls, "expected update_status to be called"
    return calls[-1].kwargs.get("skip_reason")


def _online_result(executor, deps, events, track):
    return executor._handle_run_success(_params(), "/out", 1.0, None, pre_run_count=0)


def _batch_completed_result(executor, deps, events, track):
    """Drive the real caller: a batch whose jobs have finished and been processed."""
    deps.batch_manager.handle_batch_agent.return_value = ("/out", "completed")
    with patch.object(ActionExecutor, "_compute_batch_wall_clock", return_value=1.0):
        return executor._handle_batch_check(ACTION, 0, CONFIG, datetime.now())


def _batch_passthrough_result(executor, deps, events, track):
    return executor._handle_run_success(_params(), "/out", 1.0, "passthrough", pre_run_count=0)


PATHS = {
    "online": _online_result,
    "batch_completed": _batch_completed_result,
    "batch_passthrough": _batch_passthrough_result,
}


def _run(path, executor, deps):
    events: list = []
    with (
        patch("agent_actions.workflow.executor.fire_event", side_effect=events.append),
        patch.object(ActionExecutor, "_track_action_complete") as track,
    ):
        result = PATHS[path](executor, deps, events, track)
    return result, events, track


class TestGuardFilteredAllIsClassifiedInEveryMode:
    @pytest.mark.parametrize("path", ["online", "batch_completed", "batch_passthrough"])
    def test_status_is_skipped(self, path, executor, deps):
        _all_records_guard_filtered(deps)
        result, _, _ = _run(path, executor, deps)
        assert result.status == ActionStatus.SKIPPED

    @pytest.mark.parametrize("path", ["online", "batch_completed", "batch_passthrough"])
    def test_skip_reason_is_recorded_for_the_downstream_cascade(self, path, executor, deps):
        _all_records_guard_filtered(deps)
        _run(path, executor, deps)
        assert _skip_reason_of(deps) == GUARD_FILTERED_ALL

    @pytest.mark.parametrize("path", ["online", "batch_completed", "batch_passthrough"])
    def test_an_action_skip_event_announces_the_skip(self, path, executor, deps):
        _all_records_guard_filtered(deps)
        _, events, _ = _run(path, executor, deps)
        skips = [e for e in events if isinstance(e, ActionSkipEvent)]
        assert len(skips) == 1
        assert skips[0].skip_reason == GUARD_FILTERED_ALL

    @pytest.mark.parametrize("path", ["online", "batch_completed", "batch_passthrough"])
    def test_the_skip_is_tracked_not_counted_as_a_completion(self, path, executor, deps):
        _all_records_guard_filtered(deps)
        _, _, track = _run(path, executor, deps)
        assert track.call_count == 1
        assert track.call_args.args[2] == ActionStatus.SKIPPED
        assert track.call_args.kwargs.get("skip_reason") == GUARD_FILTERED_ALL


class TestNothingElseIsReclassifiedAsSkipped:
    """A blanket 'mark it SKIPPED' fix must fail these."""

    @pytest.mark.parametrize("path", ["online", "batch_completed", "batch_passthrough"])
    def test_a_clean_run_still_completes(self, path, executor, deps):
        _all_records_guard_filtered(deps, filtered=False)
        result, _, _ = _run(path, executor, deps)
        assert result.status == ActionStatus.COMPLETED

    @pytest.mark.parametrize("path", ["online", "batch_completed", "batch_passthrough"])
    def test_a_clean_run_records_no_skip_reason(self, path, executor, deps):
        _all_records_guard_filtered(deps, filtered=False)
        _run(path, executor, deps)
        assert _skip_reason_of(deps) is None

    @pytest.mark.parametrize("path", ["online", "batch_completed", "batch_passthrough"])
    def test_a_clean_run_fires_no_skip_event(self, path, executor, deps):
        _all_records_guard_filtered(deps, filtered=False)
        _, events, _ = _run(path, executor, deps)
        assert [e for e in events if isinstance(e, ActionSkipEvent)] == []

    def test_total_failure_in_batch_still_resolves_as_failed(self, executor, deps):
        deps.action_runner.storage_backend.has_disposition.return_value = False
        deps.action_runner.storage_backend.get_failed_items.return_value = [
            {"record_id": "guid-1", "disposition": "failed", "reason": "503"}
        ]
        deps.action_runner.storage_backend.has_successful_items.return_value = False
        result, _, _ = _run("batch_completed", executor, deps)
        assert result.status == ActionStatus.FAILED
        assert result.success is False
