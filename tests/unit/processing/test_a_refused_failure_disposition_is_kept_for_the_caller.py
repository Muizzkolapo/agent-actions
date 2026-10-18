"""Collection keeps, for its caller, the error a store refused a record's failure with.

Online raises it once the file is stored: it stamps no ``deferred`` a later run could
settle the failure from, so the action fails instead of leaving the record holding
nothing that ``agac retry`` can find (1534). Batch keeps its ``deferred`` marks instead.
"""

import sqlite3

import pytest

from agent_actions.errors import DispositionsNotStoredError, is_action_fatal
from agent_actions.processing.result_collector import collect_results_from_processing_results
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"


class RefusingBackend(SQLiteBackend):
    def set_dispositions_batch(self, rows):
        raise sqlite3.OperationalError("database or disk is full")


@pytest.fixture
def backend(tmp_path):
    db = RefusingBackend.create(db_path=str(tmp_path / "store.db"), workflow_name="wf")
    db.initialize()
    yield db
    db.close()


def _collect(backend, results):
    context = ProcessingContext(agent_config={}, agent_name=ACTION, storage_backend=backend)
    collect_results_from_processing_results(
        results, ACTION, storage_backend=backend, context=context
    )
    return context


def _answered(guid: str) -> ProcessingResult:
    return ProcessingResult.success(
        data=[{"source_guid": guid, "content": {ACTION: {"summary": "s"}}}], source_guid=guid
    )


@pytest.mark.parametrize(
    "failure",
    [
        ProcessingResult.failed(error="boom", source_guid="lost"),
        ProcessingResult.exhausted(error="spent", source_guid="lost"),
    ],
    ids=["failed", "exhausted"],
)
def test_a_refused_failure_is_kept_as_an_error_fatal_to_the_action(backend, failure):
    context = _collect(backend, [_answered("kept"), failure])

    error = context.failure_not_stored
    assert isinstance(error, DispositionsNotStoredError)
    assert is_action_fatal(error)
    assert "database or disk is full" in str(error)
    assert "lost" in str(error)
    assert context.dispositions_not_stored >= {"lost"}


def test_a_refusal_holding_no_failure_keeps_no_error(backend):
    context = _collect(
        backend, [_answered("kept"), ProcessingResult.filtered(source_guid="filtered")]
    )

    assert context.failure_not_stored is None
    assert "filtered" in context.dispositions_not_stored


def test_a_stored_failure_keeps_no_error(tmp_path):
    db = SQLiteBackend.create(db_path=str(tmp_path / "store.db"), workflow_name="wf")
    db.initialize()
    try:
        context = _collect(db, [ProcessingResult.failed(error="boom", source_guid="stored")])
    finally:
        db.close()

    assert context.failure_not_stored is None
    assert context.dispositions_not_stored == set()
