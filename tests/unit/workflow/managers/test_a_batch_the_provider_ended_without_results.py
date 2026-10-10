"""A file whose batch the provider ended without results costs its records, not the action.

A batch the provider failed or cancelled before it finished returns nothing, and no later
pass can read it. Passed over, a failed one held the action waiting for good and a
cancelled one let it complete with the file's records still deferred, where `agac retry`
does not look.

Driven through the harness of the collect-pass tests beside this one: the real lifecycle
manager, job manager, registry and collect pass over a SQLite store, with each entry's
status as the poll before the pass recorded it.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.core.batch_constants import BatchStatus, RecoveryType
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_FAILED
from tests.unit.workflow.managers.test_a_file_the_collect_pass_could_not_read import (
    ACTION,
    PAGES,
    _Action,
)

ENDED = [BatchStatus.FAILED, BatchStatus.CANCELLED]


def _action(tmp_path, ended: str, collected: tuple[str, ...] = ()) -> _Action:
    """page2.json's batch ended *ended*; the other files' batches finished."""
    action = _Action(tmp_path, collected=collected, statuses={"page2.json": ended})
    for name in PAGES:
        action.send(name, f"{name}-a", f"{name}-b")
    return action


@pytest.mark.parametrize("ended", ENDED)
def test_the_action_completes_past_it(tmp_path, ended):
    """Nothing will come back for it: waiting on it holds the action for good."""
    action = _action(tmp_path, ended)

    assert action.check() == (action.out, "completed")
    assert action.finalized == ["page1.json", "page3.json"]


@pytest.mark.parametrize("ended", ENDED)
def test_the_records_of_its_file_are_marked_failed(tmp_path, ended):
    """Left deferred, they are failed nowhere `agac retry` looks."""
    action = _action(tmp_path, ended)

    action.check()

    assert action.dispositions() == {
        "page2.json-a": DISPOSITION_FAILED,
        "page2.json-b": DISPOSITION_FAILED,
    }


@pytest.mark.parametrize("ended", ENDED)
def test_an_action_left_waiting_on_it_after_the_others_were_collected_completes(tmp_path, ended):
    """The pass reads nothing else, which is not an error, and must not read as waiting."""
    action = _action(tmp_path, ended, collected=("page1.json", "page3.json"))

    assert action.check() == (action.out, "completed")
    assert action.finalized == []
    assert set(action.dispositions().values()) == {DISPOSITION_FAILED}


@pytest.mark.parametrize("ended", ENDED)
def test_the_run_names_the_file_and_its_batch(tmp_path, ended, caplog):
    action = _action(tmp_path, ended)

    with caplog.at_level(logging.WARNING, logger="agent_actions.llm.batch.services.processing"):
        action.check()

    assert "Could not read page2.json (batch batch-page2.json)" in caplog.text


@pytest.mark.parametrize("ended", ENDED)
def test_a_run_after_it_finds_nothing_owed(tmp_path, ended):
    """Settled, the entry is no batch to pause for, and a pass after reads it no more."""
    action = _action(tmp_path, ended)
    action.check()

    assert action.lifecycle.check_batch_submission(ACTION, 0, tmp_path) != "batch_submitted"
    assert action.check() == (action.out, "completed")
    assert action.finalized == ["page1.json", "page3.json"]


def _store_fails_once_to_read(monkeypatch, file_name: str) -> None:
    """The store cannot be read for *file_name*'s context map the first time it is asked."""
    load = BatchContextManager.load_batch_context_map
    failed: list[str] = []

    def load_once(backend, action_name, batch_name):
        if batch_name == file_name and not failed:
            failed.append(batch_name)
            raise ProcessingError("database is locked")
        return load(backend, action_name, batch_name)

    monkeypatch.setattr(BatchContextManager, "load_batch_context_map", staticmethod(load_once))


def _sent_and_deferred(tmp_path, ended: str) -> _Action:
    """As submission leaves them: page2.json's records deferred on its batch."""
    action = _action(tmp_path, ended)
    for record_id in ("page2.json-a", "page2.json-b"):
        action.backend.set_disposition(ACTION, record_id, DISPOSITION_DEFERRED)
    return action


@pytest.mark.parametrize("ended", ENDED)
def test_a_pass_that_could_not_reach_its_records_waits_for_it(tmp_path, ended, monkeypatch):
    """Settled with its records still deferred, the action completes with no failure for
    `agac retry` to find, and nothing comes back for them."""
    action = _sent_and_deferred(tmp_path, ended)
    _store_fails_once_to_read(monkeypatch, "page2.json")

    assert action.check() == (None, "in_progress")
    assert set(action.dispositions().values()) == {DISPOSITION_DEFERRED}
    assert action.lifecycle.check_batch_submission(ACTION, 0, tmp_path) == "batch_submitted"


@pytest.mark.parametrize("ended", ENDED)
def test_a_pass_that_could_not_reach_its_records_does_not_say_they_were_failed(
    tmp_path, ended, monkeypatch, caplog
):
    action = _sent_and_deferred(tmp_path, ended)
    _store_fails_once_to_read(monkeypatch, "page2.json")

    with caplog.at_level(logging.WARNING, logger="agent_actions.llm.batch.services.processing"):
        action.check()

    assert "Could not read page2.json (batch batch-page2.json)" in caplog.text
    assert "marked failed for `agac retry`" not in caplog.text


@pytest.mark.parametrize("ended", ENDED)
def test_the_run_after_it_marks_them_failed_and_completes(tmp_path, ended, monkeypatch):
    action = _sent_and_deferred(tmp_path, ended)
    _store_fails_once_to_read(monkeypatch, "page2.json")
    action.check()

    assert action.check() == (action.out, "completed")
    assert action.dispositions() == {
        "page2.json-a": DISPOSITION_FAILED,
        "page2.json-b": DISPOSITION_FAILED,
    }
    assert action.finalized == ["page1.json", "page3.json"]


def test_a_pass_in_which_every_batch_ended_still_fails_the_action(tmp_path):
    """Nothing came back for any file, and the run after sends every file again."""
    action = _Action(tmp_path, statuses=dict.fromkeys(PAGES, BatchStatus.FAILED))
    for name in PAGES:
        action.send(name, f"{name}-a")

    with pytest.raises(ProcessingError, match="No batch results were successfully processed"):
        action.check()
    assert set(action.dispositions().values()) == {DISPOSITION_FAILED}


def test_a_repair_round_the_provider_failed_leaves_the_records_of_its_file_alone(tmp_path):
    """The pass over its file reads that file again and answers its records, which the
    round's failure must not then mark failed."""
    action = _Action(tmp_path)
    action.send("page3.json", "page3.json-a", "page3.json-b")
    action.register(
        BatchJobEntry(
            batch_id="batch-page3.json_repair_1",
            status=BatchStatus.FAILED,
            timestamp="2026-10-04T09:10:00+00:00",
            provider="agac-provider",
            record_count=1,
            file_name="page3.json_repair_1",
            parent_file_name="page3.json",
            recovery_type=RecoveryType.REPAIR,
            recovery_attempt=1,
        )
    )

    action.check()

    assert "page3.json" in action.finalized
    assert action.dispositions() == {}
