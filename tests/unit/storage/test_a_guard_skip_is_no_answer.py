"""A guard skip is no answer, so the disposition gate never carries one as done (1348).

Before 1348 an online run recorded a guard skip as ``passthrough``, which is terminal, and a
store it wrote still holds those rows. The guard runs above the gate, so a record reaching
the gate is one the guard passes now: carrying its stored tombstone would answer it with a
skip. An empty answer kept as a tombstone (``on_empty: skip``) is an answer, and stays done.
"""

import pytest

from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.record.reasons import EMPTY_OUTPUT, GUARD_SKIP
from agent_actions.storage.backend import (
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"


@pytest.fixture
def backend(tmp_path):
    db = SQLiteBackend.create(db_path=str(tmp_path / "store.db"), workflow_name="wf")
    db.initialize()
    db.set_disposition(ACTION, "skipped-before-1348", DISPOSITION_PASSTHROUGH, reason=GUARD_SKIP)
    db.set_disposition(ACTION, "skipped", DISPOSITION_UNPROCESSED, reason=GUARD_SKIP)
    db.set_disposition(ACTION, "empty", DISPOSITION_PASSTHROUGH, reason=EMPTY_OUTPUT)
    db.set_disposition(ACTION, "answered", DISPOSITION_SUCCESS)
    db.set_disposition(
        ACTION, NODE_LEVEL_RECORD_ID, DISPOSITION_PASSTHROUGH, reason="All records tombstoned"
    )
    yield db
    db.close()


def test_only_an_answer_is_terminal(backend):
    assert backend.get_terminal_record_ids(ACTION) == {"empty", "answered"}


def test_the_gate_sends_on_a_record_the_guard_skipped_before_and_passes_now(backend):
    records = [
        {"source_guid": guid} for guid in ("skipped-before-1348", "skipped", "empty", "answered")
    ]

    to_process, carried = DispositionGate(backend).filter(records, ACTION)

    assert [record["source_guid"] for record in to_process] == ["skipped-before-1348", "skipped"]
    assert carried == {"empty", "answered"}
