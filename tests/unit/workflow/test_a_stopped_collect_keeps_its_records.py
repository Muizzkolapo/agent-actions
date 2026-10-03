"""A collect pass stopped by an error, as the next process finds it.

The status file is all that crosses from the run that was stopped to the run that
resets it, and the dispositions are what the reset decides. Both are real here.
"""

from __future__ import annotations

import pytest

from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_FAILED,
    DISPOSITION_SUCCESS,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from tests.unit.workflow.test_coordinator_interrupt import EXECUTION_ORDER, _build_workflow


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    # One file collected and written, one still at the provider, one record that failed.
    store.set_disposition("agent_a", "collected", DISPOSITION_SUCCESS)
    store.set_disposition("agent_a", "waiting", DISPOSITION_DEFERRED)
    store.set_disposition("agent_a", "broken", DISPOSITION_FAILED)
    return store


def _stopped(tmp_path, status: ActionStatus) -> None:
    """The run that was stopped: its error handler marks what was in flight as failed."""
    manager = ActionStateManager(tmp_path / ".agent_status.json", EXECUTION_ORDER)
    manager.update_status("agent_a", status)
    manager.mark_running_as_failed()


def _next_run_resets(tmp_path, backend) -> ActionStateManager:
    """The next process: a state manager read from the file, and the reset it runs first."""
    manager = ActionStateManager(tmp_path / ".agent_status.json", EXECUTION_ORDER)
    workflow = _build_workflow(manager)
    workflow.storage_backend = backend
    workflow._reset_retryable_actions()
    return manager


def _dispositions(backend) -> dict[str, str]:
    return {row["record_id"]: row["disposition"] for row in backend.get_disposition("agent_a")}


def test_the_file_it_had_collected_is_still_done_for_the_next_run(tmp_path, backend):
    _stopped(tmp_path, ActionStatus.CHECKING_BATCH)

    manager = _next_run_resets(tmp_path, backend)

    assert _dispositions(backend) == {"collected": DISPOSITION_SUCCESS}
    assert manager.get_status("agent_a") == ActionStatus.PENDING


def test_an_action_that_failed_while_running_is_still_wiped(tmp_path, backend):
    _stopped(tmp_path, ActionStatus.RUNNING)

    _next_run_resets(tmp_path, backend)

    assert _dispositions(backend) == {}


def test_the_mark_does_not_outlive_the_reset_it_was_for(tmp_path, backend):
    """Read back from the file, as the process after next would."""
    _stopped(tmp_path, ActionStatus.CHECKING_BATCH)
    _next_run_resets(tmp_path, backend)

    later = ActionStateManager(tmp_path / ".agent_status.json", EXECUTION_ORDER)

    assert later.stopped_collecting("agent_a") is False


def test_a_later_failure_while_running_is_wiped_though_an_earlier_one_was_collecting(
    tmp_path, backend
):
    _stopped(tmp_path, ActionStatus.CHECKING_BATCH)
    _next_run_resets(tmp_path, backend)
    backend.set_disposition("agent_a", "collected", DISPOSITION_SUCCESS)
    _stopped(tmp_path, ActionStatus.RUNNING)

    _next_run_resets(tmp_path, backend)

    assert _dispositions(backend) == {}


def test_agac_retry_drops_the_mark_though_it_runs_no_reset(tmp_path, backend):
    """Retry sets the status itself. Left on, the mark would make a later failure of the
    same action, while running, look like a collect pass and keep what it should wipe."""
    _stopped(tmp_path, ActionStatus.CHECKING_BATCH)
    retrying = ActionStateManager(tmp_path / ".agent_status.json", EXECUTION_ORDER)
    retrying.update_status("agent_a", ActionStatus.PENDING)
    _stopped(tmp_path, ActionStatus.RUNNING)

    _next_run_resets(tmp_path, backend)

    assert _dispositions(backend) == {}


def test_an_action_left_out_of_the_reset_keeps_its_mark_for_when_it_is_reset(tmp_path):
    _stopped(tmp_path, ActionStatus.CHECKING_BATCH)
    manager = ActionStateManager(tmp_path / ".agent_status.json", EXECUTION_ORDER)

    manager.reset_retryable(exclude={"agent_a"})

    later = ActionStateManager(tmp_path / ".agent_status.json", EXECUTION_ORDER)
    assert later.stopped_collecting("agent_a") is True
    assert later.get_status("agent_a") == ActionStatus.FAILED
