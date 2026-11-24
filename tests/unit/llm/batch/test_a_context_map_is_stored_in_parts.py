"""A batch's context map is stored in parts, so saving it never builds one string of it.

The map keeps each submitted record's input row, which collection rebuilds the output
from. It was saved as one JSON string: a temporary copy about the size of the file's
input, the largest part of the batch step's peak memory (#1865). Each part now holds
the entries of a few megabytes, and the map reads back exactly as one string read back.
"""

from __future__ import annotations

import gc
import sqlite3
import tracemalloc
from typing import Any

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.infrastructure import context as context_module
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils import deep_json

ACTION = "summarise"
FILE = "sub/page.json"
KEY = f"batch_context:{ACTION}:{FILE}"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def _deep(levels: int) -> Any:
    value: Any = "bottom"
    for _ in range(levels):
        value = {"down": value}
    return value


def _context_map(records: int, text: int = 2_000) -> dict[str, Any]:
    """Entries as preparation leaves them: the input row and the batch's own fields."""
    return {
        f"t{index}": {
            "target_id": f"t{index}",
            "source_guid": f"g{index}",
            "content": {
                "extract": {"page": f"{index} é ☃ " + "p" * text, "score": index / 3},
                "nested": {"1": [None, True, 1.5e300, {"k": "v"}]},
            },
            "_batch_filter_status": "included",
            "_batch_passthrough_fields": {"n": index},
        }
        for index in range(records)
    }


def _keys(backend: SQLiteBackend) -> list[str]:
    return backend.list_metadata_prefix(KEY)


def test_a_map_reads_back_as_one_string_reads_back(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 10_000)
    context_map = _context_map(40)
    context_map["t3"]["content"]["deep"] = _deep(1_200)

    BatchContextManager.save_batch_context_map(backend, ACTION, context_map, FILE)
    loaded = BatchContextManager.load_batch_context_map(backend, ACTION, FILE)

    as_one_string = deep_json.loads(deep_json.dumps(context_map, ensure_ascii=False))
    # Compared as text: == recurses once per level, and one entry is deeper than that.
    assert deep_json.dumps(loaded) == deep_json.dumps(as_one_string)
    assert len(_keys(backend)) > 5, "the map was not split"


def test_saving_a_map_never_holds_one_string_of_it(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 200_000, raising=False)
    context_map = _context_map(600, text=20_000)
    whole = len(deep_json.dumps(context_map, ensure_ascii=False))
    gc.collect()
    tracemalloc.start()
    try:
        start = tracemalloc.get_traced_memory()[0]
        BatchContextManager.save_batch_context_map(backend, ACTION, context_map, FILE)
        peak = tracemalloc.get_traced_memory()[1] - start
    finally:
        tracemalloc.stop()

    assert peak < whole / 4, (peak, whole)
    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == context_map


def test_a_map_that_was_never_saved_is_not_found_and_the_error_names_fresh(backend):
    with pytest.raises(ProcessingError, match=r"Context map not found.*--fresh"):
        BatchContextManager.load_batch_context_map(backend, ACTION, FILE)


def test_saving_again_leaves_nothing_of_the_last_save(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 10_000)
    BatchContextManager.save_batch_context_map(backend, ACTION, _context_map(40), FILE)
    smaller = _context_map(3)

    BatchContextManager.save_batch_context_map(backend, ACTION, smaller, FILE)

    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == smaller
    assert len(_keys(backend)) == 2, _keys(backend)  # the key naming the parts, and one part


def test_deleting_a_map_or_the_batch_state_removes_every_part(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 10_000)
    BatchContextManager.save_batch_context_map(backend, ACTION, _context_map(40), FILE)
    assert BatchContextManager.delete_batch_context_map(backend, ACTION, FILE) is True
    assert _keys(backend) == []

    BatchContextManager.save_batch_context_map(backend, ACTION, _context_map(40), FILE)
    backend.clear_batch_state(ACTION)
    assert _keys(backend) == []


def test_an_empty_map_reads_back_empty(backend):
    BatchContextManager.save_batch_context_map(backend, ACTION, {}, FILE)

    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == {}


class _FailsAfter:
    """The real store, whose metadata writes fail after a number of them."""

    def __init__(self, backend: SQLiteBackend, writes: int) -> None:
        self._backend = backend
        self.writes = writes

    def save_metadata(self, key: str, value: str) -> None:
        if self.writes == 0:
            raise OSError("disk full")
        self.writes -= 1
        self._backend.save_metadata(key, value)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)


def test_a_save_that_fails_part_way_leaves_the_last_map_whole(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 10_000)
    earlier = _context_map(10)
    BatchContextManager.save_batch_context_map(backend, ACTION, earlier, FILE)
    keys_before = _keys(backend)

    with pytest.raises(ProcessingError, match="Failed to save context map"):
        BatchContextManager.save_batch_context_map(
            _FailsAfter(backend, writes=3),  # type: ignore[arg-type]
            ACTION,
            _context_map(40),
            FILE,
        )

    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == earlier
    assert _keys(backend) == keys_before


def test_a_part_that_is_gone_is_named(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 10_000)
    BatchContextManager.save_batch_context_map(backend, ACTION, _context_map(40), FILE)
    parts = [key for key in _keys(backend) if not key.endswith("#parts")]
    backend.delete_metadata(parts[-1])

    with pytest.raises(ProcessingError, match="part"):
        BatchContextManager.load_batch_context_map(backend, ACTION, FILE)


def test_a_save_that_fails_to_name_its_parts_leaves_the_last_map_whole(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 10_000)
    earlier = _context_map(10)
    BatchContextManager.save_batch_context_map(backend, ACTION, earlier, FILE)
    keys_before = _keys(backend)
    newer = _context_map(40)
    parts = len(list(context_module._encoded_parts(newer)))

    with pytest.raises(ProcessingError, match="Failed to save context map"):
        BatchContextManager.save_batch_context_map(
            _FailsAfter(backend, writes=parts),  # type: ignore[arg-type]
            ACTION,
            newer,
            FILE,
        )

    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == earlier
    assert _keys(backend) == keys_before


class _CommitFailsOnce:
    """The store's connection, whose first commit after naming the parts fails."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._armed = False

    def execute(self, sql: str, params: Any = ()) -> Any:
        if any("#parts" in str(value) for value in params):
            self._armed = True
        return self._connection.execute(sql, params)

    def commit(self) -> None:
        if self._armed:
            self._armed = False
            raise sqlite3.OperationalError("disk I/O error")
        self._connection.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def test_a_save_whose_parts_key_fails_to_commit_leaves_the_last_map_whole(backend, monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 10_000)
    earlier = _context_map(10)
    BatchContextManager.save_batch_context_map(backend, ACTION, earlier, FILE)
    keys_before = _keys(backend)
    connection = backend._connection
    backend._connection = _CommitFailsOnce(connection)

    with pytest.raises(ProcessingError, match="Failed to save context map"):
        BatchContextManager.save_batch_context_map(backend, ACTION, _context_map(40), FILE)

    backend._connection = connection
    assert BatchContextManager.load_batch_context_map(backend, ACTION, FILE) == earlier
    assert _keys(backend) == keys_before
