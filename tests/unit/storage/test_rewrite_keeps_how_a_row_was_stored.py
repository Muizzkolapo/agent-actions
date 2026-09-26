"""How a row was stored has to reach the caller rewriting it.

``read_target_for_rewrite`` reconstructs, and reconstruction drops
``_delta_mode``. Re-deriving the mode covers the row whose identity nothing
upstream holds, but not the row stored whole under an identity its upstream does
hold — a producer's own stamp, which the re-derivation cannot see and would
rewrite as a delta.

Marking is per row, not per identity: ``source_guid`` is a content hash, so an
action can hold several rows under one, and their modes differ routinely — a
duplicate that produced no output for this action is stored whole while its twin
is stored as a delta. Marking by identity would freeze the delta row's upstream
namespaces at the moment of the rewrite.
"""

from __future__ import annotations

import json

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

UPSTREAM = {"source": {"t": "v1"}, "a1": {"v": 1}}


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "probe")
    b.initialize()
    b.save_metadata("execution_order", json.dumps(["a1", "a2"]))
    b.save_metadata("dependency_graph", json.dumps({"a1": [], "a2": ["a1"]}))
    b.write_target(
        "a1",
        "f.json",
        [
            {
                "source_guid": "G0",
                "_state": "processed",
                "_schema_version": 1,
                "content": dict(UPSTREAM),
            }
        ],
    )
    return b


def _stored(backend):
    return [r.get("_delta_mode") for r in backend._read_target_raw("a2", "f.json")]


def test_a_row_stored_whole_comes_back_marked(backend):
    backend.write_target(
        "a2",
        "f.json",
        [
            {
                "source_guid": "MINTED",
                "_state": "processed",
                "_schema_version": 1,
                "_delta_mode": "full",
                "content": {**UPSTREAM, "a2": {"x": 1}},
            }
        ],
    )

    assert [r.get("_delta_mode") for r in backend.read_target_for_rewrite("a2", "f.json")] == [
        "full"
    ]


def test_a_row_stored_as_a_delta_comes_back_unmarked(backend):
    """Otherwise the rewrite stores it whole and freezes its upstream content."""
    backend.write_target(
        "a2",
        "f.json",
        [
            {
                "source_guid": "G0",
                "_state": "processed",
                "_schema_version": 1,
                "content": {**UPSTREAM, "a2": {"x": 1}},
            }
        ],
    )
    assert _stored(backend) == ["delta"]

    assert [r.get("_delta_mode") for r in backend.read_target_for_rewrite("a2", "f.json")] == [None]


def test_two_rows_under_one_identity_keep_their_own_modes(backend):
    """The case an identity-keyed mark gets wrong: one guid, two modes."""
    backend.write_target(
        "a2",
        "f.json",
        [
            {
                "source_guid": "G0",
                "_state": "processed",
                "_schema_version": 1,
                "_delta_mode": "full",
                "content": {**UPSTREAM, "a2": {"x": 1}},
            },
            {
                "source_guid": "G0",
                "_state": "processed",
                "_schema_version": 1,
                "content": {**UPSTREAM, "a2": {"x": 2}},
            },
        ],
    )
    assert _stored(backend) == ["full", "delta"]

    handed_back = [r.get("_delta_mode") for r in backend.read_target_for_rewrite("a2", "f.json")]

    assert handed_back == ["full", None]


def test_a_delta_row_rewritten_still_follows_its_upstream(backend):
    """The consequence, end to end: a row marked whole would keep `v1` after
    upstream became `v2`, because a whole row joins nothing on read."""
    backend.write_target(
        "a2",
        "f.json",
        [
            {
                "source_guid": "G0",
                "_state": "processed",
                "_schema_version": 1,
                "content": {**UPSTREAM, "a2": {"x": 1}},
            }
        ],
    )
    backend.write_target("a2", "f.json", backend.read_target_for_rewrite("a2", "f.json"))
    backend.write_target(
        "a1",
        "f.json",
        [
            {
                "source_guid": "G0",
                "_state": "processed",
                "_schema_version": 1,
                "content": {"source": {"t": "v2"}, "a1": {"v": 2}},
            },
        ],
    )

    read_back = backend.read_target("a2", "f.json")[0]

    assert read_back["content"]["source"] == {"t": "v2"}
    assert read_back["content"]["a1"] == {"v": 2}
