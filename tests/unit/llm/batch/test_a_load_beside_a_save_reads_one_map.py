"""A load that a save of the same file's map overtakes reads the new map, whole.

`agac batch retrieve` takes no run lock, so it can load a map while `agac run` saves the
same file's map again. The save deletes the parts the load is reading. The load then
reads the parts key again and loads the parts it names now.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.infrastructure import context as context_module
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "a"
FILE = "g.json"


@pytest.fixture(autouse=True)
def small_parts(monkeypatch):
    monkeypatch.setattr(context_module, "_PART_CHARS", 1_000)


@pytest.fixture
def stores(tmp_path):
    """Two connections to one store: the run's, and the retrieve command's."""
    writer = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    writer.initialize()
    reader = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    reader.initialize()
    yield writer, reader
    reader.close()
    writer.close()


def _context_map(tag: str, records: int = 20) -> dict[str, Any]:
    return {f"t{index}": {"row": f"{tag}-{index}", "pad": "x" * 200} for index in range(records)}


class _SavesWhileItLoads:
    """The reader's store; before it reads a part, the writer saves the map again."""

    def __init__(self, reader: SQLiteBackend, writer: SQLiteBackend, saves: list[str]) -> None:
        self._reader = reader
        self._writer = writer
        self.saves = saves

    def load_metadata(self, key: str) -> str | None:
        is_part = "#" in key and not key.endswith("#parts")
        if is_part and self.saves:
            BatchContextManager.save_batch_context_map(
                self._writer, ACTION, _context_map(self.saves.pop(0)), FILE
            )
        return self._reader.load_metadata(key)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._reader, name)


def test_the_steps_of_a_load_that_a_save_overtakes_find_a_part_gone(stores):
    """The sequence the loader must survive."""
    writer, reader = stores
    BatchContextManager.save_batch_context_map(writer, ACTION, _context_map("A"), FILE)
    key = BatchContextManager._metadata_key(ACTION, FILE)
    parts = context_module._part_keys(reader, key)
    assert parts

    BatchContextManager.save_batch_context_map(writer, ACTION, _context_map("B"), FILE)

    assert reader.load_metadata(parts[0]) is None


def test_a_load_that_a_save_overtakes_reads_the_new_map(stores):
    writer, reader = stores
    BatchContextManager.save_batch_context_map(writer, ACTION, _context_map("A"), FILE)

    loaded = BatchContextManager.load_batch_context_map(
        _SavesWhileItLoads(reader, writer, ["B"]),  # type: ignore[arg-type]
        ACTION,
        FILE,
    )

    assert loaded == _context_map("B")


def test_a_load_that_two_saves_overtake_reads_the_last_map(stores):
    writer, reader = stores
    BatchContextManager.save_batch_context_map(writer, ACTION, _context_map("A"), FILE)

    loaded = BatchContextManager.load_batch_context_map(
        _SavesWhileItLoads(reader, writer, ["B", "C"]),  # type: ignore[arg-type]
        ACTION,
        FILE,
    )

    assert loaded == _context_map("C")


def test_a_load_that_saves_overtake_each_time_stops(stores):
    writer, reader = stores
    BatchContextManager.save_batch_context_map(writer, ACTION, _context_map("A"), FILE)

    with pytest.raises(ProcessingError, match="saved again"):
        BatchContextManager.load_batch_context_map(
            _SavesWhileItLoads(reader, writer, ["B", "C", "D", "E", "F"]),  # type: ignore[arg-type]
            ACTION,
            FILE,
        )


def test_a_part_gone_while_the_parts_key_stays_is_named(stores):
    writer, reader = stores
    BatchContextManager.save_batch_context_map(writer, ACTION, _context_map("A"), FILE)
    key = BatchContextManager._metadata_key(ACTION, FILE)
    parts = context_module._part_keys(reader, key)
    assert parts
    writer.delete_metadata(parts[-1])

    with pytest.raises(ProcessingError, match="is missing"):
        BatchContextManager.load_batch_context_map(reader, ACTION, FILE)
