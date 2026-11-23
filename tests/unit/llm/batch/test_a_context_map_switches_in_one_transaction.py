"""A save names its parts and deletes the map saved whole in one store transaction.

Thus the parts key and a map saved whole exist together only when an earlier version
saved the map whole after this version saved parts (a downgrade, then an upgrade
again). The loader then reads the map saved whole: it is the newer one.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.infrastructure import context as context_module
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "a"
FILE = "g.json"
WHOLE_KEY = f"batch_context:{ACTION}:{FILE}"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def _rows(backend: SQLiteBackend) -> dict[str, str]:
    rows = backend.connection.execute(
        "SELECT key, value FROM workflow_metadata WHERE key LIKE 'batch_context:%'"
    ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def _context_map(row: str, records: int = 1) -> dict[str, Any]:
    return {f"t{index}": {"row": row, "pad": "x" * 200} for index in range(records)}


def test_a_map_an_earlier_version_saved_whole_after_the_parts_wins(backend):
    BatchContextManager.save_batch_context_map(backend, ACTION, {"t1": {"row": "OLD"}}, FILE)
    # An earlier version saves a newer map whole, and leaves the parts key as it stood.
    backend.save_metadata(WHOLE_KEY, json.dumps({"t1": {"row": "NEW"}}))

    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == {
        "t1": {"row": "NEW"}
    }


def test_the_next_save_removes_the_stale_parts_and_the_map_saved_whole(backend):
    BatchContextManager.save_batch_context_map(backend, ACTION, {"t1": {"row": "OLD"}}, FILE)
    stale_parts = {key for key in _rows(backend) if not key.endswith("#parts")}
    backend.save_metadata(WHOLE_KEY, json.dumps({"t1": {"row": "NEW"}}))

    BatchContextManager.save_batch_context_map(backend, ACTION, {"t1": {"row": "NEWEST"}}, FILE)

    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == {
        "t1": {"row": "NEWEST"}
    }
    rows = _rows(backend)
    assert WHOLE_KEY not in rows
    assert stale_parts and not stale_parts & set(rows), rows
    assert len(rows) == 2, rows  # the parts key and one part


def _fail_when_deleting(backend: SQLiteBackend, key: str) -> None:
    """Make the store refuse to delete *key*: a failure inside the transaction."""
    backend.connection.execute(
        "CREATE TRIGGER refuse_delete BEFORE DELETE ON workflow_metadata "
        f"WHEN old.key = '{key}' BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
    )
    backend.connection.commit()


@pytest.mark.parametrize("earlier_parts", [False, True])
def test_a_save_that_fails_between_the_parts_key_and_the_delete_changes_nothing(
    backend, monkeypatch, earlier_parts
):
    monkeypatch.setattr(context_module, "_PART_CHARS", 1_000)
    if earlier_parts:
        BatchContextManager.save_batch_context_map(backend, ACTION, _context_map("PARTS", 9), FILE)
    backend.save_metadata(WHOLE_KEY, json.dumps(_context_map("WHOLE", 3)))
    before = _rows(backend)
    _fail_when_deleting(backend, WHOLE_KEY)

    with pytest.raises(ProcessingError, match="Failed to save context map"):
        BatchContextManager.save_batch_context_map(backend, ACTION, _context_map("NEW", 9), FILE)

    assert _rows(backend) == before
    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == _context_map(
        "WHOLE", 3
    )


def test_a_map_saved_whole_alone_still_loads(backend):
    backend.save_metadata(WHOLE_KEY, json.dumps(_context_map("WHOLE", 3)))

    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == _context_map(
        "WHOLE", 3
    )


def test_a_map_in_parts_alone_still_loads(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 1_000)
    BatchContextManager.save_batch_context_map(backend, ACTION, _context_map("PARTS", 9), FILE)

    assert WHOLE_KEY not in _rows(backend)
    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == _context_map(
        "PARTS", 9
    )


class TestTheStoreSavesAndDeletesInOneTransaction:
    def test_all_of_it_lands(self, backend):
        backend.save_metadata("gone", "1")

        backend.save_and_delete_metadata({"kept": "2", "also": "3"}, ["gone", "never_there"])

        assert backend.load_metadata("kept") == "2"
        assert backend.load_metadata("also") == "3"
        assert backend.load_metadata("gone") is None

    def test_a_failure_lands_none_of_it(self, backend):
        backend.save_metadata("gone", "1")
        backend.save_metadata("kept", "old")
        _fail_when_deleting(backend, "gone")

        with pytest.raises(sqlite3.Error, match="injected failure"):
            backend.save_and_delete_metadata({"kept": "new", "added": "x"}, ["gone"])

        assert backend.load_metadata("kept") == "old"
        assert backend.load_metadata("added") is None
        assert backend.load_metadata("gone") == "1"
        backend.save_metadata("after", "ok")  # no transaction is left open
        assert backend.load_metadata("after") == "ok"

    def test_it_clears_the_caches_save_metadata_clears(self, backend):
        backend.save_metadata("execution_order", json.dumps(["x"]))
        assert backend._get_execution_order() == ["x"]

        backend.save_and_delete_metadata({"execution_order": json.dumps(["y"])}, [])

        assert backend._get_execution_order() == ["y"]
