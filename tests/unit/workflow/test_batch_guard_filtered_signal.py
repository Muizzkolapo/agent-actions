"""An all-removed action must read the same in batch and online.

Batch never reaches the writer of the node-level ``skipped`` disposition —
``workflow/pipeline.py`` forks to ``_handle_batch_mode`` and returns first — so
it records a node-level ``passthrough`` for its empty tombstone instead.  That
row cannot be swapped for ``skipped``: it is the batch resume path's only
marker, and ``_has_blocking_disposition`` clears a node-level ``skipped`` as
stale while target files exist, which they do.  So the classifier reads it.

Every test builds the state through the real backend's own write APIs and
routes it through the real executor.  Nothing is mocked into existence — the
defect these guard against was a fix that routed a signal batch never emits.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.logging.events.workflow_events import ActionSkipEvent
from agent_actions.processing.result_collector import write_node_level_disposition
from agent_actions.record.reasons import GUARD_FILTERED_ALL
from agent_actions.storage.backend import DISPOSITION_PASSTHROUGH
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "extract_candidates"
CHUNK = "dbt_pages.json"
CONFIG = {"kind": "llm", "run_mode": "batch"}


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"), workflow_name="wf")
    b.initialize()
    return b


def _batch_filtered_every_record(backend, records=()):
    """Reproduce what workflow/pipeline.py leaves behind for a tombstoned action.

    ``write_target`` derives record_count from the list, so an empty tombstone
    is what makes the action's record count zero — the fix's discriminator.
    """
    backend.write_target(ACTION, CHUNK, list(records))
    write_node_level_disposition(backend, ACTION, DISPOSITION_PASSTHROUGH, "All records tombstoned")


def _executor(backend):
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.action_runner = MagicMock()
    deps.action_runner.storage_backend = backend
    deps.action_runner.execution_order = [ACTION, "author_stem"]
    return ActionExecutor(deps)


def _params():
    return ActionRunParams(
        action_name=ACTION,
        action_idx=0,
        action_config=CONFIG,
        is_last_action=False,
        start_time=datetime.now(),
    )


def _drive(executor, deps, resume: bool):
    """Route real storage state through the real executor, first run or resume."""
    events: list = []
    with patch("agent_actions.workflow.executor.fire_event", side_effect=events.append):
        if resume:
            deps.batch_manager.handle_batch_agent.return_value = ("/out", "completed")
            with patch.object(ActionExecutor, "_compute_batch_wall_clock", return_value=1.0):
                result = executor._handle_batch_check(ACTION, 0, CONFIG, datetime.now())
        else:
            result = executor._handle_run_success(
                _params(), "/out", 1.0, "passthrough", pre_run_count=0
            )
    return result, events


@pytest.mark.parametrize("resume", [False, True], ids=["first_run", "resume"])
class TestTheRealBatchSignalReachesTheUser:
    """Signal to routing, end to end — the link no other test covers."""

    def test_it_resolves_as_skipped(self, resume, backend):
        _batch_filtered_every_record(backend)
        ex = _executor(backend)
        result, _ = _drive(ex, ex.deps, resume)
        assert result.status == ActionStatus.SKIPPED

    def test_the_cli_is_given_a_reason_to_print(self, resume, backend):
        _batch_filtered_every_record(backend)
        ex = _executor(backend)
        _drive(ex, ex.deps, resume)
        assert (
            ex.deps.state_manager.update_status.call_args.kwargs["skip_reason"]
            == GUARD_FILTERED_ALL
        )

    def test_the_skip_is_announced(self, resume, backend):
        _batch_filtered_every_record(backend)
        ex = _executor(backend)
        _, events = _drive(ex, ex.deps, resume)
        assert [e.skip_reason for e in events if isinstance(e, ActionSkipEvent)] == [
            GUARD_FILTERED_ALL
        ]

    def test_the_resume_marker_survives(self, resume, backend):
        """The classifier reads the row; it must never consume it."""
        _batch_filtered_every_record(backend)
        ex = _executor(backend)
        _drive(ex, ex.deps, resume)
        assert backend.has_disposition(ACTION, DISPOSITION_PASSTHROUGH)

    def test_it_still_reports_itself_as_a_batch_action(self, resume, backend):
        """The renderer appends "(batch)" from this; both rounds must agree."""
        _batch_filtered_every_record(backend)
        ex = _executor(backend)
        _drive(ex, ex.deps, resume)
        assert ex.deps.state_manager.update_status.call_args.kwargs.get("execution_mode") == "batch"

    def test_an_action_that_produced_records_still_completes(self, resume, backend):
        """A tombstone carrying real records is a passthrough, not a skip."""
        _batch_filtered_every_record(backend, records=[{"id": 1}, {"id": 2}])
        ex = _executor(backend)
        result, events = _drive(ex, ex.deps, resume)
        assert result.status == ActionStatus.COMPLETED
        assert [e for e in events if isinstance(e, ActionSkipEvent)] == []


class TestTheDiscriminatorIsTheRealRecordCount:
    """M-2: prove write_target([]) really is what makes the count zero."""

    def test_an_empty_tombstone_leaves_a_zero_record_count(self, backend):
        _batch_filtered_every_record(backend)
        assert _executor(backend)._count_records_for_action(ACTION) == 0

    def test_a_populated_tombstone_does_not(self, backend):
        _batch_filtered_every_record(backend, records=[{"id": 1}, {"id": 2}])
        assert _executor(backend)._count_records_for_action(ACTION) == 2


class TestNothingElseBecomesASkip:
    def test_an_action_with_no_dispositions_completes(self, backend):
        backend.write_target(ACTION, CHUNK, [])
        assert _executor(backend)._resolve_completion_status(ACTION) == ActionStatus.COMPLETED

    def test_a_record_level_passthrough_alone_is_not_a_node_level_skip(self, backend):
        backend.write_target(ACTION, CHUNK, [])
        backend.set_disposition(
            action_name=ACTION,
            record_id="guid-1",
            disposition=DISPOSITION_PASSTHROUGH,
            reason="guard_skip",
        )
        assert _executor(backend)._resolve_completion_status(ACTION) == ActionStatus.COMPLETED
