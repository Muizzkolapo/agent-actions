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

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.storage.backend import DISPOSITION_FAILED
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
