"""An action counts as waiting on a batch while one is not collected, whatever reset it (#1921).

A check that stops with its batch out leaves the action to be reset to pending. Without
a batch still out, a pending action is not waiting, and is not marked for another pass.
"""

from types import SimpleNamespace

import pytest

from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import ActionExecutor
from agent_actions.workflow.managers.state import ActionStatus

ACTION = "tag"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _sent(backend, *, status: str, collected: bool) -> None:
    BatchRegistryManager(backend, ACTION).save_batch_job(
        "pages.json",
        BatchJobEntry(
            batch_id="batch-1",
            status=status,
            timestamp="2026-11-28T00:00:00+00:00",
            provider="openai",
            file_name="pages.json",
            collected_at="2026-11-28T00:01:00+00:00" if collected else None,
        ),
    )


def _waits(backend, status: ActionStatus) -> bool:
    executor = SimpleNamespace(
        deps=SimpleNamespace(action_runner=SimpleNamespace(storage_backend=backend))
    )
    return ActionExecutor._waits_on_a_batch(executor, ACTION, status)


@pytest.mark.parametrize("status", [ActionStatus.BATCH_SUBMITTED, ActionStatus.CHECKING_BATCH])
def test_a_status_that_names_a_batch_counts_as_waiting(backend, status):
    assert _waits(backend, status)


@pytest.mark.parametrize(
    "status", [ActionStatus.PENDING, ActionStatus.INTERRUPTED, ActionStatus.FAILED]
)
def test_a_reset_action_with_a_batch_not_collected_counts_as_waiting(backend, status):
    _sent(backend, status="in_progress", collected=False)

    assert _waits(backend, status)


@pytest.mark.parametrize(
    "status", [ActionStatus.PENDING, ActionStatus.INTERRUPTED, ActionStatus.FAILED]
)
def test_a_reset_action_with_no_batch_out_does_not(backend, status):
    assert not _waits(backend, status)


@pytest.mark.parametrize(
    ("batch_status", "collected"), [("completed", True), ("failed", False), ("cancelled", False)]
)
def test_a_collected_or_ended_batch_is_not_waited_on(backend, batch_status, collected):
    _sent(backend, status=batch_status, collected=collected)

    assert not _waits(backend, ActionStatus.PENDING)


def test_a_completed_action_is_not_waiting(backend):
    _sent(backend, status="in_progress", collected=False)

    assert not _waits(backend, ActionStatus.COMPLETED)
