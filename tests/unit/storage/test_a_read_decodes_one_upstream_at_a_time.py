"""Reading a stored file holds one upstream's decoded rows at a time, not every upstream's.

A delta row keeps its whole envelope (its state history among it) and only its own
namespace. To rebuild a file, the store joins the namespaces of every action above it.
It decoded every upstream file at once, envelopes included, and kept them all until
the join ended, though it takes only each row's content. Deep in a long workflow that
was several times the file it returned (#1865). A write measured the upstream the same
way, to tell which rows are joinable.
"""

from __future__ import annotations

import gc
import json
import tracemalloc
from collections.abc import Callable
from typing import Any

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTIONS = [f"a{index:02d}" for index in range(16)]
FILE = "f.json"
RECORDS = 40
ENVELOPE = 20_000
FIELD = 1_000


def _rows(depth: int) -> list[dict[str, Any]]:
    """The rows of the action at *depth*: every namespace above it, and a large envelope."""
    rows = []
    for index in range(RECORDS):
        content: dict[str, Any] = {"source": {"id": index}}
        for name in ACTIONS[: depth + 1]:
            content[name] = {"text": f"{name}:{index} " + "t" * FIELD}
        rows.append(
            {
                "source_guid": f"g{index}",
                "_state": "processed",
                "_schema_version": 1,
                "history": f"{depth}:{index} " + "h" * ENVELOPE,
                "content": content,
            }
        )
    return rows


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "probe")
    store.initialize()
    store.save_metadata("execution_order", json.dumps(ACTIONS))
    store.save_metadata(
        "dependency_graph",
        json.dumps({name: ACTIONS[:depth] for depth, name in enumerate(ACTIONS)}),
    )
    for depth, name in enumerate(ACTIONS[:-1]):
        store.write_target(name, FILE, _rows(depth), is_first_action=depth == 0)
    store._reconstruction_cache.clear()
    yield store
    store.close()


def _measured(work: Callable[[], Any]) -> tuple[Any, int]:
    """What *work* returns, and the most memory it held above where it started."""
    gc.collect()
    tracemalloc.start()
    try:
        start = tracemalloc.get_traced_memory()[0]
        result = work()
        peak = tracemalloc.get_traced_memory()[1] - start
    finally:
        tracemalloc.stop()
    return result, peak


def _every_upstream_decoded_at_once(backend: SQLiteBackend) -> int:
    """What the decoded rows of every upstream file take, held together."""
    gc.collect()
    tracemalloc.start()
    try:
        start = tracemalloc.get_traced_memory()[0]
        upstream = backend._read_target_raw_batch(ACTIONS[:-1], FILE)
        held = tracemalloc.get_traced_memory()[0] - start
    finally:
        tracemalloc.stop()
    del upstream
    return held


def test_a_read_holds_far_less_than_every_upstream_decoded(backend):
    last = ACTIONS[-1]
    backend.write_target(last, FILE, _rows(len(ACTIONS) - 1))
    backend._reconstruction_cache.clear()
    all_at_once = _every_upstream_decoded_at_once(backend)

    rows, peak = _measured(lambda: backend.read_target(last, FILE))

    assert [sorted(row["content"]) for row in rows] == [sorted(["source", *ACTIONS])] * RECORDS
    assert rows[7]["content"]["a03"]["text"].startswith("a03:7 ")
    assert peak < all_at_once / 2, (peak, all_at_once)


def test_a_write_holds_far_less_than_every_upstream_decoded(backend):
    all_at_once = _every_upstream_decoded_at_once(backend)
    rows = _rows(len(ACTIONS) - 1)

    _, peak = _measured(lambda: backend.write_target(ACTIONS[-1], FILE, rows))

    backend._reconstruction_cache.clear()
    stored = backend._read_target_raw(ACTIONS[-1], FILE)
    # Every row is joinable, so each is stored as a delta of its own namespace.
    assert {row["_delta_mode"] for row in stored} == {"delta"}
    assert peak < all_at_once / 2, (peak, all_at_once)
