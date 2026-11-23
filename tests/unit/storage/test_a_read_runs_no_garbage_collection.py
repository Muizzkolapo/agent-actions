"""Reading a stored file pauses the cyclic garbage collector, and gives it back as it was.

A read decodes and joins every upstream namespace of a file: many new objects, none of
them in a cycle, so reference counting frees them all. Each collection the read set off
walked the whole heap. On a synthetic run with 30 earlier actions, collections took a
fifth of the batch step's time, almost all of it inside reads (#1865).

The collector is process-wide and the actions of a step read on their own threads, so
the pause is counted: it ends when the last read ends, and only resumes a collector that
ran when the first read began.
"""

from __future__ import annotations

import gc
import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.gc_pause import collector_paused

ACTIONS = [f"a{index:02d}" for index in range(8)]
FILE = "f.json"


def _rows(depth: int, records: int = 200) -> list[dict[str, Any]]:
    return [
        {
            "source_guid": f"g{index}",
            "_state": "processed",
            "_schema_version": 1,
            "content": {
                "source": {"id": index},
                **{
                    name: {"items": [f"{name}{index}-{k}" for k in range(5)]}
                    for name in ACTIONS[: depth + 1]
                },
            },
        }
        for index in range(records)
    ]


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "probe")
    store.initialize()
    store.save_metadata("execution_order", json.dumps(ACTIONS))
    store.save_metadata(
        "dependency_graph",
        json.dumps({name: ACTIONS[:depth] for depth, name in enumerate(ACTIONS)}),
    )
    for depth, name in enumerate(ACTIONS):
        store.write_target(name, FILE, _rows(depth), is_first_action=depth == 0)
    store._reconstruction_cache.clear()
    yield store
    store.close()


@pytest.fixture
def collections() -> Iterator[list[int]]:
    """The generation of each collection that runs, from any thread."""
    ran: list[int] = []

    def note(phase: str, info: dict[str, Any]) -> None:
        if phase == "stop":
            ran.append(info["generation"])

    gc.collect()
    gc.callbacks.append(note)
    try:
        yield ran
    finally:
        gc.callbacks.remove(note)


@pytest.fixture(autouse=True)
def collector_enabled() -> Iterator[None]:
    was = gc.isenabled()
    gc.enable()
    yield
    if not was:
        gc.disable()


def test_a_read_runs_no_collection(backend, collections):
    rows = backend.read_target(ACTIONS[-1], FILE)

    assert len(rows) == 200
    assert sorted(rows[0]["content"]) == sorted(["source", *ACTIONS])
    # The objects the read made are counted while it runs, so the first allocation after
    # it may set off one young collection; none ran inside it.
    assert collections in ([], [0]), collections
    assert gc.isenabled()


def test_a_read_leaves_a_stopped_collector_stopped(backend):
    gc.disable()

    backend.read_target(ACTIONS[-1], FILE)

    assert not gc.isenabled()


def test_a_read_that_fails_gives_the_collector_back(backend):
    with pytest.raises(FileNotFoundError):
        backend.read_target(ACTIONS[-1], "missing.json")

    assert gc.isenabled()


def test_the_collector_resumes_when_the_last_of_two_overlapping_pauses_ends():
    first_in = threading.Event()
    second_in = threading.Event()
    first_out = threading.Event()

    def first() -> None:
        with collector_paused():
            first_in.set()
            second_in.wait(5)
        first_out.set()

    thread = threading.Thread(target=first)
    thread.start()
    first_in.wait(5)
    with collector_paused():
        second_in.set()
        first_out.wait(5)
        # The first pause ended while this one runs: the collector stays paused.
        assert not gc.isenabled()
    thread.join(5)

    assert gc.isenabled()


def test_a_pause_inside_a_pause_resumes_only_at_the_outer_end():
    with collector_paused():
        with collector_paused():
            assert not gc.isenabled()
        assert not gc.isenabled()
    assert gc.isenabled()
