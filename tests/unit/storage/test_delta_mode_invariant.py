"""A delta-mode row always carries dict content.

``_reconstruct_from_deltas`` guards against a delta row whose content is
missing, and that guard cannot fire because ``_extract_delta`` stores anything
without usable content as a full record instead. These tests pin the invariant
so the guard stays explicable rather than looking like dead code.
"""

from __future__ import annotations

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "probe")
    b.initialize()
    return b


NOT_USABLE_AS_A_DELTA = [
    pytest.param({"source_guid": "g", "content": None}, id="content-is-none"),
    pytest.param({"source_guid": "g"}, id="content-absent"),
    pytest.param({"source_guid": "g", "content": "text"}, id="content-not-a-dict"),
    pytest.param({"content": {"act": {"x": 1}}}, id="no-source-guid"),
    pytest.param({"source_guid": "g", "content": {"other": {}}}, id="action-not-in-content"),
    pytest.param(
        {"source_guid": "g", "content": None, "_delta_mode": "delta"},
        id="caller-claims-delta-but-content-is-none",
    ),
]


@pytest.mark.parametrize("record", NOT_USABLE_AS_A_DELTA)
def test_a_record_without_usable_content_is_stored_whole(backend, record):
    assert backend._extract_delta(dict(record), "act")["_delta_mode"] == "full"


def test_a_well_formed_record_becomes_a_delta(backend):
    stored = backend._extract_delta(
        {"source_guid": "g", "content": {"act": {"x": 1}, "upstream": {"y": 2}}}, "act"
    )

    assert stored["_delta_mode"] == "delta"
    assert stored["content"] == {"act": {"x": 1}}


@pytest.mark.parametrize("record", NOT_USABLE_AS_A_DELTA)
def test_no_shape_produces_a_delta_row_the_reconstruction_guard_would_catch(backend, record):
    stored = backend._extract_delta(dict(record), "act")
    is_delta = stored.get("_delta_mode") not in ("first", "full", None)

    assert not (is_delta and stored.get("content") is None)
