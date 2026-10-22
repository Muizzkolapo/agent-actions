"""A FILE tool handed its whole file again writes every row again. One it writes as it
stands is the row it was: it keeps the identifiers it was stored under, and what the
actions below hold for it still answers, so their dispositions for it are kept.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.processing.disposition_gate import rows_written_again_unchanged
from agent_actions.workflow.pipeline import _forget_answers_below


def _row(guid: str | None, summary: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source_guid": guid,
        "_state": "processed",
        "content": {"roll_up": {"summary": summary}, "source": {"page": summary}},
        "target_id": f"target-{summary}-{extra.pop('run', 1)}",
        "node_id": f"roll_up_{summary}",
        "lineage": [f"flatten_{summary}", f"roll_up_{summary}"],
        "_state_history": [{"to": "processed", "timestamp": summary}],
    }
    if guid is None:
        del row["source_guid"]
    row.update(extra)
    return row


class TestWhichRowsAreTheRowsTheyWere:
    def test_a_row_written_as_it_stands_is_put_back_as_stored(self):
        stored = [_row("b", "beta", run=1)]
        produced = [_row("b", "beta", run=2)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == {"b"}
        assert out[0]["target_id"] == "target-beta-1"
        assert out[0]["_state_history"] == stored[0]["_state_history"]

    def test_a_row_written_differently_is_the_new_row(self):
        stored = [_row("b", "beta (1 of 1)", run=1)]
        produced = [_row("b", "beta (2 of 2)", run=2)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert out[0]["content"]["roll_up"]["summary"] == "beta (2 of 2)"
        assert out[0]["target_id"] == "target-beta (2 of 2)-2"

    def test_only_what_a_run_mints_may_differ(self):
        """The identifiers and the history's stamps; everything else is what the row holds."""
        stored = [_row("b", "beta", run=1, _delta_mode="full")]
        produced = [_row("b", "beta", run=2)]
        produced[0]["lineage"] = ["other"]
        produced[0]["_state_history"] = []

        _, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == {"b"}

    @pytest.mark.parametrize(
        "differs",
        [
            {"_state": "failed"},
            {"parent_target_id": "another"},
            {"producer_source_guids": ["x"]},
            {"metadata": {"model": "other"}},
            {"_tombstone": True},
        ],
        ids=lambda d: next(iter(d)),
    )
    def test_a_row_differing_in_what_it_holds_is_new(self, differs):
        stored = [_row("b", "beta", run=1)]
        produced = [_row("b", "beta", run=2, **differs)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert out[0] is produced[0]

    def test_a_tombstone_answered_with_a_row_is_new(self):
        stored = [_row("a", "alpha", run=1, _state="cascade_skipped", _tombstone=True)]
        stored[0]["content"] = {"roll_up": None, "source": {"page": "alpha"}}
        produced = [_row("a", "alpha", run=2)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert out[0]["_state"] == "processed"

    def test_the_rows_keep_their_order_and_number(self):
        stored = [_row("a", "alpha"), _row("b", "beta")]
        produced = [_row("b", "beta", run=2), _row("a", "alpha (changed)", run=2)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert [r["source_guid"] for r in out] == ["b", "a"]
        assert unchanged == {"b"}

    def test_a_row_the_file_did_not_hold_is_new(self):
        out, unchanged = rows_written_again_unchanged([_row("a", "alpha")], [])

        assert unchanged == frozenset()
        assert out[0]["source_guid"] == "a"

    def test_a_nameless_row_is_never_the_row_it_was(self):
        stored = [_row(None, "roll")]
        produced = [_row(None, "roll", run=2)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert out[0]["target_id"] == "target-roll-2"

    @pytest.mark.parametrize("twice", ["stored", "produced"])
    def test_an_identity_held_by_several_rows_is_never_unchanged(self, twice):
        """Which of them is which is 615's question; neither is put back."""
        stored = [_row("b", "beta")] * (2 if twice == "stored" else 1)
        produced = [_row("b", "beta", run=2)] * (2 if twice == "produced" else 1)

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert all(r["target_id"] == "target-beta-2" for r in out)


class _Backend:
    """Holds one file per action below, and records what is cleared."""

    def __init__(self, below: dict[str, list[dict[str, Any]]]) -> None:
        self._below = below
        self.cleared: dict[str, list[str]] = {}

    def read_target_for_rewrite(self, action_name: str, relative_path: str) -> list[dict]:
        try:
            return self._below[action_name]
        except KeyError:
            raise FileNotFoundError(relative_path) from None

    def clear_dispositions_batch(self, action_name: str, record_ids: list[str]) -> None:
        self.cleared.setdefault(action_name, []).extend(record_ids)


def _below(guid: str, **named: Any) -> dict[str, Any]:
    return {"source_guid": guid, "_state": "processed", **named}


class TestWhatIsForgottenBelow:
    REPLACED = [_row("a", "alpha"), _row("b", "beta")]
    INPUTS = [{"source_guid": "a"}, {"source_guid": "b"}]

    def test_with_nothing_unchanged_every_identity_is_cleared(self):
        backend = _Backend({"final": [_below("a"), _below("b")]})

        _forget_answers_below(backend, ["final"], "p.json", self.REPLACED, self.INPUTS)

        assert backend.cleared == {"final": ["a", "b"]}

    def test_an_unchanged_record_keeps_its_answer_below(self):
        backend = _Backend({"final": [_below("a"), _below("b")]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"b"})
        )

        assert backend.cleared == {"final": ["a"]}

    def test_a_row_minted_from_an_unchanged_record_alone_is_kept(self):
        backend = _Backend({"final": [_below("m1", producer_source_guids=["b"])]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"b"})
        )

        assert backend.cleared == {"final": ["a"]}

    def test_a_row_minted_from_a_changed_record_too_is_forgotten(self):
        backend = _Backend({"final": [_below("m1", producer_source_guids=["a", "b"])]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"b"})
        )

        assert backend.cleared == {"final": ["a", "m1"]}

    def test_a_row_keeping_an_unchanged_identity_but_built_on_a_changed_record_is_forgotten(self):
        """A FILE tool below can keep one input's identity and name the others it consumed.
        Its row for beta was computed from alpha too, so beta's answer there is gone."""
        backend = _Backend({"final": [_below("b", producer_source_guids=["a"])]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"b"})
        )

        assert backend.cleared == {"final": ["a", "b"]}

    def test_a_row_naming_an_unchanged_parent_is_kept(self):
        backend = _Backend({"final": [_below("m2", parent_source_guid="b")]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"b"})
        )

        assert backend.cleared == {"final": ["a"]}

    def test_a_row_built_on_nothing_the_file_held_is_forgotten(self):
        """A roll-up below names no record of the file; nothing vouches for it."""
        backend = _Backend({"final": [_below("r1")]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"a", "b"})
        )

        assert backend.cleared == {"final": ["r1"]}

    def test_every_action_below_is_cleared_the_same_identities(self):
        backend = _Backend({"final": [_below("a"), _below("b")], "grand": [_below("a")]})

        _forget_answers_below(
            backend, ["final", "grand"], "p.json", self.REPLACED, self.INPUTS, frozenset({"b"})
        )

        assert backend.cleared == {"final": ["a"], "grand": ["a"]}

    def test_with_every_row_unchanged_nothing_is_cleared(self):
        backend = _Backend({"final": [_below("a"), _below("b")]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"a", "b"})
        )

        assert backend.cleared == {}
