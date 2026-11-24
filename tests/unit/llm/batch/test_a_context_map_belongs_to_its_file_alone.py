"""Saving or deleting one file's context map leaves every other file's map whole.

The keys of a map start with ``batch_context:{action}:`` and the file's name. One file's
name can begin with another's (``page.json`` and ``page.json2``), and a name can hold
``#`` or ``:``. A save or a delete that matched keys by prefix, or a part key that a
file's name could spell, would reach the map of another file.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.infrastructure import context as context_module
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarise"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


@pytest.fixture(autouse=True)
def small_parts(monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 1_000)


def _context_map(tag: str, records: int = 20) -> dict[str, Any]:
    return {
        f"t{index}": {"target_id": f"t{index}", "content": {"row": f"{tag}-{index}-" + "x" * 200}}
        for index in range(records)
    }


def _save(backend: SQLiteBackend, file_name: str, context_map: dict[str, Any]) -> None:
    BatchContextManager.save_batch_context_map(backend, ACTION, context_map, file_name)


def _load(backend: SQLiteBackend, file_name: str) -> dict[str, Any]:
    return BatchContextManager.load_batch_context_map(backend, ACTION, file_name)


def test_saving_a_file_again_leaves_a_file_whose_name_it_begins(backend):
    other = _context_map("other")
    _save(backend, "page.json", _context_map("first"))
    _save(backend, "page.json2", other)

    _save(backend, "page.json", _context_map("second"))

    assert _load(backend, "page.json2") == other
    assert _load(backend, "page.json") == _context_map("second")


def test_deleting_a_file_leaves_a_file_whose_name_it_begins(backend):
    other = _context_map("other")
    _save(backend, "page.json", _context_map("first"))
    _save(backend, "page.json2", other)
    _save(backend, "page.json", _context_map("second"))

    assert BatchContextManager.delete_batch_context_map(backend, ACTION, "page.json") is True

    assert _load(backend, "page.json2") == other
    remaining = backend.list_metadata_prefix(f"batch_context:{ACTION}:")
    assert remaining and all("page.json2" in key for key in remaining), remaining


def test_a_file_whose_name_holds_a_colon_leaves_the_map_its_name_begins(backend):
    first = _context_map("first")
    other = _context_map("other")
    _save(backend, "f.json", first)

    _save(backend, "f.json:000000000000:000000", other)

    assert _load(backend, "f.json") == first
    assert _load(backend, "f.json:000000000000:000000") == other
    BatchContextManager.delete_batch_context_map(backend, ACTION, "f.json:000000000000:000000")
    assert _load(backend, "f.json") == first


@pytest.mark.parametrize("name", ["f.json#parts", "f.json#000000000000:000000", "a#b.json"])
def test_a_name_that_holds_a_hash_is_refused_before_anything_is_written(backend, name):
    """A part key is the map's key, ``#`` and more; a name with ``#`` could spell one."""
    first = _context_map("first")
    _save(backend, "f.json", first)
    keys = backend.list_metadata_prefix(f"batch_context:{ACTION}:")

    with pytest.raises(ValueError, match="'#'"):
        _save(backend, name, _context_map("other"))
    with pytest.raises(ProcessingError, match="'#'"):
        _load(backend, name)
    with pytest.raises(ValueError, match="'#'"):
        BatchContextManager.delete_batch_context_map(backend, ACTION, name)

    assert backend.list_metadata_prefix(f"batch_context:{ACTION}:") == keys
    assert _load(backend, "f.json") == first


def test_the_store_refuses_a_staging_or_output_file_whose_name_holds_a_hash(backend):
    """So no run reaches a batch with such a name: the file is refused when it is stored."""
    with pytest.raises(ValueError, match="Invalid characters in relative_path"):
        backend.write_source("f.json#parts", [{"source_guid": "g", "content": {}}])
    with pytest.raises(ValueError, match="Invalid characters in relative_path"):
        backend.write_target("act", "f.json#parts", [{"source_guid": "g", "content": {}}])


def test_the_batch_state_reset_removes_every_key(backend):
    _save(backend, "f.json", _context_map("first"))
    _save(backend, "f.json2", _context_map("other"))
    assert backend.list_metadata_prefix(f"batch_context:{ACTION}:")

    backend.clear_batch_state(ACTION)

    assert backend.list_metadata_prefix(f"batch_context:{ACTION}:") == []
