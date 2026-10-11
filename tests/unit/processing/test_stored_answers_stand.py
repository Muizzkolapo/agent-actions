"""Whether a run that failed and answered nothing leaves an online file as it is stored.

The online pipelines ask it before they decide not to write a file. A store that cannot
answer fails the action, as one that cannot write does: lost per file, the file would stay
unwritten over the answers a reset took back.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import is_action_fatal
from agent_actions.processing.disposition_gate import stored_answers_stand
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"
FILE = "pages1.json"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    store._write_target_raw(
        ACTION,
        FILE,
        [{"source_guid": "r1", "_state": "processed", "_delta_mode": "full"}],
    )
    store._reconstruction_cache.clear()
    yield store
    store.close()


def test_answers_their_records_still_hold_as_done_stand(backend):
    backend.set_disposition(ACTION, "r1", "success")

    assert stored_answers_stand(backend, ACTION, FILE)


def test_answers_a_reset_took_back_do_not(backend):
    assert not stored_answers_stand(backend, ACTION, FILE)


def test_nothing_stored_leaves_nothing_to_stand_over(backend):
    assert stored_answers_stand(backend, ACTION, "pages2.json")


@pytest.mark.parametrize("read", ["read_target_for_rewrite", "get_disposition"])
def test_a_store_that_cannot_be_read_fails_the_action(backend, read):
    """Raised per file, the walk would go on and the action complete over the old rows."""
    setattr(backend, read, MagicMock(side_effect=sqlite3.OperationalError("database is locked")))

    with pytest.raises(sqlite3.OperationalError) as raised:
        stored_answers_stand(backend, ACTION, FILE)

    assert is_action_fatal(raised.value)
