"""What a repair takes out below an action that rewrote rows, over the real store.

The CLI tests in `tests/integration/test_a_retry_answers_what_a_split_writes_below_it.py`
drive the whole retry; these pin the edges no fixture there reaches.
"""

import pytest

from agent_actions.processing.repair_lineage import (
    drop_rows_built_on_rows_gone_above,
    gone_above,
    keep_notes_at,
    note_rewritten_by_repair,
    notes_kept_at,
    resume_notes,
    written_above,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _row(guid, *, parent=None, producers=None, state="processed"):
    row = {
        "source_guid": guid,
        "target_id": f"t-{guid}",
        "_state": state,
        "_delta_mode": "full",
        "content": {"below": {"summary": guid}},
    }
    if parent:
        row["parent_source_guid"] = parent
    if producers:
        row["producer_source_guids"] = producers
    return row


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), "wf")
    store.initialize()
    yield store
    store.close()


def _guids(backend, action="below", path="p.json"):
    return [row["source_guid"] for row in backend.read_target_for_rewrite(action, path)]


def test_what_an_action_wrote_and_took_away_is_noted_for_each_action_below(backend):
    note_rewritten_by_repair(
        backend,
        ["below", "further"],
        [_row("record"), _row("other")],
        [_row("half-1"), _row("half-2"), _row("other")],
    )

    for action in ("below", "further"):
        assert written_above(backend, action) == {"half-1", "half-2"}
        assert gone_above(backend, action) == {"record"}
    assert written_above(backend, "beside") == frozenset()


def test_rows_built_on_a_gone_row_are_taken_out_with_their_dispositions(backend):
    note_rewritten_by_repair(backend, ["below"], [_row("record"), _row("split-1")], [])
    backend.write_target(
        "below",
        "p.json",
        [
            _row("record", state="cascade_skipped"),
            _row("minted", parent="staged", producers=["split-1"]),
            _row("kept", parent="staged", producers=["split-9"]),
        ],
    )
    for guid in ("record", "split-1", "kept"):
        backend.set_disposition("below", guid, "success")

    before = drop_rows_built_on_rows_gone_above(backend, "below", "p.json", [], ())

    assert [row["source_guid"] for row in before] == ["record", "minted", "kept"]
    assert _guids(backend) == ["kept"]
    assert {row["record_id"] for row in backend.get_disposition("below")} == {"kept"}


def test_a_gone_identity_still_among_the_unnamed_inputs_is_left_alone(backend):
    """Another branch still hands it to this action, and the repair does not ask for
    it again, so nothing would write its row back."""
    note_rewritten_by_repair(backend, ["below"], [_row("shared")], [])
    backend.write_target("below", "p.json", [_row("shared")])
    backend.set_disposition("below", "shared", "success")

    drop_rows_built_on_rows_gone_above(backend, "below", "p.json", [_row("shared")], ())

    assert _guids(backend) == ["shared"]
    assert [row["record_id"] for row in backend.get_disposition("below")] == ["shared"]


def test_nothing_is_written_when_nothing_above_was_taken_away(backend):
    backend.write_target("below", "p.json", [_row("kept")])

    before = drop_rows_built_on_rows_gone_above(backend, "below", "p.json", [], ())

    assert [row["source_guid"] for row in before] == ["kept"]
    assert _guids(backend) == ["kept"]


def test_kept_notes_go_back_only_to_the_actions_named_and_only_for_their_retry(backend, tmp_path):
    kept = tmp_path / "notes.json"
    keep_notes_at(backend, kept, "retry-1")
    note_rewritten_by_repair(backend, ["below", "further"], [_row("record")], [_row("half-1")])

    assert notes_kept_at(kept, "retry-2") == {}
    assert notes_kept_at(tmp_path / "missing.json", "retry-1") == {}
    notes = notes_kept_at(kept, "retry-1")
    assert notes["gone"] == {"below": ["record"], "further": ["record"]}
    assert notes["written"] == {"below": ["half-1"], "further": ["half-1"]}

    resumed = SQLiteBackend(str(tmp_path / "other.db"), "wf")
    resumed.initialize()
    try:
        resume_notes(resumed, notes, {"further"})
        assert gone_above(resumed, "further") == {"record"}
        assert written_above(resumed, "further") == {"half-1"}
        assert gone_above(resumed, "below") == frozenset()
    finally:
        resumed.close()


def test_notes_resumed_are_kept_again_under_the_retry_resuming_them(backend, tmp_path):
    kept = tmp_path / "notes.json"
    resume_notes(backend, {"gone": {"below": ["record"]}, "written": {}}, {"below"})

    keep_notes_at(backend, kept, "retry-2")

    assert notes_kept_at(kept, "retry-2")["gone"] == {"below": ["record"]}
