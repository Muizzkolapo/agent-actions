"""A FILE tool handed its whole file again writes every row again. One it writes as it
stands is the row it was: it keeps the identifiers it was stored under, and what the
actions below hold for it still answers, so their dispositions for it are kept.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent_actions.processing.disposition_gate import (
    guard_skips_as_stored,
    rows_written_again_unchanged,
)
from agent_actions.processing.types import ProcessingContext
from agent_actions.workflow.pipeline import (
    _forget_answers_below,
    _vouch_under_the_identity_put_back,
)


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

    def test_the_node_ids_of_the_rows_it_was_made_from_are_not_what_it_holds(self):
        """`lineage_sources` names upstream rows by node id, which a run mints again for
        a row an action keeps (1876): like `lineage`, it never decides a put-back."""
        stored = [_row("b", "beta", run=1, lineage_sources=["judge_1", "catalogue_1_0"])]
        produced = [_row("b", "beta", run=2, lineage_sources=["judge_2", "catalogue_2_5"])]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == {"b"}
        assert out[0]["lineage_sources"] == ["judge_1", "catalogue_1_0"]

    def test_a_row_holding_something_else_is_new_whatever_its_lineage_sources(self):
        stored = [_row("b", "beta", run=1, lineage_sources=["judge_1"])]
        produced = [_row("b", "beta (2 of 2)", run=2, lineage_sources=["judge_1"])]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert out[0] is produced[0]

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


def _child(guid: str, summary: str, record: str = "b", **extra: Any) -> dict[str, Any]:
    """A row an expanding tool wrote for *record*, minted an identity of its own."""
    return _row(
        guid,
        summary,
        parent_source_guid=record,
        producer_source_guids=[record],
        version_correlation_id=f"corr-{guid}",
        **extra,
    )


class TestARowMintedAnIdentityIsMatchedByWhatItHolds:
    def test_each_child_written_as_it_stands_is_put_back_under_its_stored_identity(self):
        stored = [_child("s1", "beta part 1", run=1), _child("s2", "beta part 2", run=1)]
        produced = [_child("n1", "beta part 1", run=2), _child("n2", "beta part 2", run=2)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == {"s1", "s2"}
        assert [row["source_guid"] for row in out] == ["s1", "s2"]
        assert [row["target_id"] for row in out] == [
            "target-beta part 1-1",
            "target-beta part 2-1",
        ]
        assert [row["version_correlation_id"] for row in out] == ["corr-s1", "corr-s2"]

    def test_a_child_written_differently_is_the_new_row(self):
        stored = [_child("s1", "beta of 1")]
        produced = [_child("n1", "beta of 2", run=2)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert out[0]["source_guid"] == "n1"

    def test_a_child_of_another_record_is_not_the_row_it_was(self):
        """The same words written for alpha are not beta's row."""
        stored = [_child("s1", "part 1", record="b")]
        produced = [_child("n1", "part 1", record="a", run=2)]

        _, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()

    @pytest.mark.parametrize("side", ["stored", "produced"])
    def test_children_holding_the_same_are_never_matched(self, side):
        """Which stored row each one was cannot be told, so neither is put back."""
        twins = {
            "stored": ([_child("s1", "same"), _child("s2", "same")], [_child("n1", "same")]),
            "produced": ([_child("s1", "same")], [_child("n1", "same"), _child("n2", "same")]),
        }
        stored, produced = twins[side]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert {row["source_guid"] for row in out} == {r["source_guid"] for r in produced}

    def test_a_stored_row_whose_identity_is_written_again_is_never_taken_by_a_minted_one(self):
        """Beta's row is written again, changed, under its identity: that is its row now."""
        stored = [_row("b", "beta", producer_source_guids=["b"])]
        produced = [
            _row("b", "beta changed", run=2, producer_source_guids=["b"]),
            _row("n1", "beta", run=2, producer_source_guids=["b"]),
        ]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert [row["source_guid"] for row in out] == ["b", "n1"]

    def test_a_row_it_holds_the_identity_of_never_matches_by_what_it_holds(self):
        """Only a row minted an identity no stored row holds is matched by content: a
        record's own row is the row stored under its identity or none."""
        stored = [_row("s1", "beta")]
        produced = [_row("b", "beta", run=2)]
        stored_b = [_row("b", "other"), *stored]

        _, unchanged = rows_written_again_unchanged(produced, stored_b)

        assert unchanged == frozenset()

    def test_an_identity_several_stored_rows_hold_is_never_put_back_for_a_minted_row(self):
        stored = [_child("s1", "part 1"), _child("s1", "part 2")]
        produced = [_child("n1", "part 1", run=2)]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()
        assert out[0]["source_guid"] == "n1"

    def test_a_correlation_a_record_carries_is_still_what_it_holds(self):
        """Only a row minted an identity is minted its correlation too."""
        stored = [_row("b", "beta", version_correlation_id="c1")]
        produced = [_row("b", "beta", run=2, version_correlation_id="c2")]

        _, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()

    def test_a_roll_up_written_as_it_stands_is_put_back(self):
        stored = [_row("r1", "alpha + beta", producer_source_guids=["a", "b"])]
        produced = [_row("r2", "alpha + beta", run=2, producer_source_guids=["a", "b"])]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == {"r1"}
        assert out[0]["target_id"] == "target-alpha + beta-1"

    def test_a_roll_up_made_from_rows_minted_again_is_put_back(self):
        stored = [_row("r1", "a + b", producer_source_guids=["a", "b"], lineage_sources=["x_1"])]
        produced = [
            _row("r2", "a + b", run=2, producer_source_guids=["a", "b"], lineage_sources=["x_2"])
        ]

        out, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == {"r1"}
        assert out[0] is stored[0]

    def test_a_roll_up_over_records_it_did_not_hold_is_new(self):
        stored = [_row("r1", "beta", producer_source_guids=["b"])]
        produced = [_row("r2", "beta", run=2, producer_source_guids=["a", "b"])]

        _, unchanged = rows_written_again_unchanged(produced, stored)

        assert unchanged == frozenset()


def _skip(guid: str, page: str, run: int = 1, **extra: Any) -> dict[str, Any]:
    """A guard skip: the input's content passed through, the action's own left out."""
    return _row(
        guid,
        page,
        run=run,
        _state="guard_skipped",
        _tombstone=True,
        node_id=f"judge_{page}_{run}",
        lineage=[f"catalogue_{page}", f"judge_{page}_{run}"],
        **extra,
    )


class TestAGuardSkipHoldingWhatItHeldIsTheRowItWas:
    """A skip answers nothing, so each run puts the record to the guard again and mints
    its row anew. One holding what the stored row holds is put back (1876), so the rows
    a FILE tool below makes from it are made from the row they were made from before."""

    def test_a_skip_holding_what_it_held_is_put_back_as_stored(self):
        stored = [_skip("b", "beta", run=1)]
        produced = [_skip("b", "beta", run=2)]

        assert guard_skips_as_stored(produced, stored) == [stored[0]]

    def test_a_skip_holding_something_else_is_the_new_row(self):
        stored = [_skip("b", "beta", run=1)]
        produced = [_skip("b", "beta changed", run=2)]

        assert guard_skips_as_stored(produced, stored) == produced

    def test_a_record_skipped_now_but_answered_before_is_the_new_row(self):
        stored = [_row("b", "beta", run=1)]
        produced = [_skip("b", "beta", run=2)]

        assert guard_skips_as_stored(produced, stored) == produced

    def test_an_answer_is_never_put_back(self):
        stored = [_row("b", "beta", run=1)]
        produced = [_row("b", "beta", run=2)]

        assert guard_skips_as_stored(produced, stored) == produced

    def test_the_rows_keep_their_order_and_number(self):
        stored = [_skip("a", "alpha"), _skip("b", "beta")]
        produced = [_row("c", "gamma", run=2), _skip("b", "beta", run=2), _skip("a", "a2", run=2)]

        out = guard_skips_as_stored(produced, stored)

        assert out == [produced[0], stored[1], produced[2]]

    @pytest.mark.parametrize("twice", ["stored", "produced"])
    def test_an_identity_held_by_several_rows_is_never_put_back(self, twice):
        stored = [_skip("b", "beta")] * (2 if twice == "stored" else 1)
        produced = [_skip("b", "beta", run=2)] * (2 if twice == "produced" else 1)

        assert guard_skips_as_stored(produced, stored) == produced


class TestWhatThisRunVouchesForARowPutBack:
    def _context(self, kept: list[tuple]) -> ProcessingContext:
        context = ProcessingContext(agent_config={}, agent_name="roll_up")
        context.kept_dispositions.extend(kept)
        return context

    def test_a_minted_identity_put_back_is_vouched_for_under_the_stored_one(self):
        produced = [_child("n1", "part 1"), _child("n2", "part 2")]
        written = [_child("s1", "part 1"), produced[1]]
        context = self._context(
            [
                ("roll_up", "n1", "success", None, None, None, None),
                ("roll_up", "n2", "success", None, None, None, None),
                ("roll_up", "b", "success", "consumed_into_output", None, None, None),
            ]
        )

        _vouch_under_the_identity_put_back(context, produced, written)

        assert [row[1] for row in context.kept_dispositions] == ["s1", "n2", "b"]
        assert context.kept_dispositions[0][2:] == ("success", None, None, None, None)

    def test_nothing_put_back_leaves_what_is_vouched_for_as_it_was(self):
        produced = [_row("b", "beta")]
        kept = [("roll_up", "b", "success", None, None, None, None)]
        context = self._context(list(kept))

        _vouch_under_the_identity_put_back(context, produced, produced)

        assert context.kept_dispositions == kept


class _Backend:
    """Holds one file per action below, and records what is cleared."""

    def __init__(
        self, below: dict[str, list[dict[str, Any]]], graph: dict[str, list[str]] | None = None
    ) -> None:
        self._below = below
        self._graph = graph
        self.cleared: dict[str, list[str]] = {}

    def load_metadata(self, key: str) -> str | None:
        return json.dumps(self._graph) if key == "dependency_graph" and self._graph else None

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
        """Under every identity it names: what it holds of beta was computed with alpha."""
        backend = _Backend({"final": [_below("m1", producer_source_guids=["a", "b"])]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"b"})
        )

        assert backend.cleared == {"final": ["a", "b", "m1"]}

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

    def test_a_row_naming_the_ancestor_its_unchanged_record_was_split_from_is_kept(self):
        """A record split above the tool carries its first ancestor as parent; the row
        below is built on the record's own row, which is unchanged, not on the ancestor."""
        replaced = [
            _row("a", "alpha", parent_source_guid="P"),
            _row("b", "beta", parent_source_guid="P"),
        ]
        inputs = [
            {"source_guid": "a", "parent_source_guid": "P"},
            {"source_guid": "b", "parent_source_guid": "P"},
        ]
        backend = _Backend({"final": [_below("b", parent_source_guid="P")]})

        _forget_answers_below(backend, ["final"], "p.json", replaced, inputs, frozenset({"b"}))

        assert backend.cleared == {"final": ["P", "a"]}

    def test_a_file_tool_below_keeps_nothing_of_a_file_that_changed_at_all(self):
        """Its every row may depend on every record of the file, so beta's row there
        was computed with alpha's, whatever it names."""
        backend = _Backend({"final": [_below("b")]})

        _forget_answers_below(
            backend,
            ["final"],
            "p.json",
            self.REPLACED,
            self.INPUTS,
            frozenset({"b"}),
            whole_file_readers=frozenset({"final"}),
        )

        assert backend.cleared == {"final": ["a", "b"]}

    def test_a_file_tool_below_keeps_what_it_holds_of_a_file_written_again_as_it_was(self):
        backend = _Backend({"final": [_below("a"), _below("b")]})

        _forget_answers_below(
            backend,
            ["final"],
            "p.json",
            self.REPLACED,
            self.INPUTS,
            frozenset({"a", "b"}),
            whole_file_readers=frozenset({"final"}),
            replacement=self.REPLACED,
        )

        assert backend.cleared == {}

    def test_a_file_tool_below_an_expansion_keeps_what_it_holds_of_a_file_as_it_was(self):
        """The children carry identities of their own; the records they came from are
        inputs of the file, not rows of it, so they never stood to be unchanged."""
        replaced = [_child("s1", "beta part 1"), _child("s2", "beta part 2")]
        backend = _Backend({"final": [_below("s1"), _below("s2")]})

        _forget_answers_below(
            backend,
            ["final"],
            "p.json",
            replaced,
            [{"source_guid": "b"}],
            frozenset({"s1", "s2"}),
            whole_file_readers=frozenset({"final"}),
            replacement=replaced,
        )

        # The record itself is cleared, which no row below carries the identity of.
        assert backend.cleared == {"final": ["b"]}

    def test_a_file_tool_below_keeps_nothing_of_a_file_holding_a_row_more(self):
        """Every stored row is unchanged, but the file now holds alpha's row too."""
        backend = _Backend({"final": [_below("b")]})

        _forget_answers_below(
            backend,
            ["final"],
            "p.json",
            [_row("b", "beta")],
            self.INPUTS,
            frozenset({"b"}),
            whole_file_readers=frozenset({"final"}),
            replacement=[_row("a", "alpha"), _row("b", "beta")],
        )

        assert backend.cleared == {"final": ["a", "b"]}

    def test_a_row_built_on_an_unchanged_child_and_naming_its_record_is_kept(self):
        """An expanding tool's rows carry identities of their own and name the record as
        parent. A row below is built on the child it carries the identity of; the record,
        an input of the file, is no row of it to be unchanged or not."""
        replaced = [_child("s1", "beta part 1"), _child("s2", "beta part 2")]
        inputs = [{"source_guid": "b"}]
        backend = _Backend(
            {
                "final": [
                    _below("s1", parent_source_guid="b", producer_source_guids=["b"]),
                    _below("s2", parent_source_guid="b", producer_source_guids=["b"]),
                ]
            }
        )

        _forget_answers_below(backend, ["final"], "p.json", replaced, inputs, frozenset({"s1"}))

        assert backend.cleared == {"final": ["b", "s2"]}

    def test_a_row_naming_only_an_input_the_file_holds_no_row_of_is_judged_by_it(self):
        """A record the tool now drops left a row below naming it alone: nothing vouches."""
        backend = _Backend({"final": [_below("x", parent_source_guid="b")]})

        _forget_answers_below(
            backend,
            ["final"],
            "p.json",
            [_child("s1", "a1", record="a")],
            [{"source_guid": "a"}, {"source_guid": "b"}],
            frozenset({"s1"}),
        )

        assert sorted(backend.cleared["final"]) == ["a", "b", "x"]

    def test_with_every_row_unchanged_nothing_is_cleared(self):
        backend = _Backend({"final": [_below("a"), _below("b")]})

        _forget_answers_below(
            backend, ["final"], "p.json", self.REPLACED, self.INPUTS, frozenset({"a", "b"})
        )

        assert backend.cleared == {}

    def test_a_file_tool_below_that_writes_its_file_again_is_cleared_alone(self):
        """`route` reads `judge` and is handed the file again; what it puts back unchanged
        decides what `answer` below it holds. Beta's answer at `judge` is built on beta's
        row alone, which is unchanged, so it stands whatever `route` names (1876)."""
        backend = _Backend(
            {
                "judge": [_below("a"), _below("b")],
                "route": [_below("P", producer_source_guids=["a", "b"])],
                "answer": [_below("P")],
            },
            graph={
                "judge": ["tool"],
                "route": ["tool", "judge"],
                "answer": ["tool", "judge", "route"],
            },
        )

        _forget_answers_below(
            backend,
            ["judge", "route", "answer"],
            "p.json",
            self.REPLACED,
            self.INPUTS,
            frozenset({"b"}),
            whole_file_readers=frozenset({"route"}),
            file_tools_run_again=frozenset({"route"}),
        )

        assert backend.cleared == {"judge": ["a"], "route": ["P", "a", "b"]}

    def test_a_file_tool_below_with_no_config_held_still_clears_every_action_below(self):
        """Not run again, it decides nothing below it, so what its rows name goes there."""
        backend = _Backend(
            {"judge": [_below("b")], "route": [_below("P", producer_source_guids=["a", "b"])]}
        )

        _forget_answers_below(
            backend,
            ["judge", "route"],
            "p.json",
            self.REPLACED,
            self.INPUTS,
            frozenset({"b"}),
            whole_file_readers=frozenset({"route"}),
        )

        assert backend.cleared == {"judge": ["P", "a", "b"], "route": ["P", "a", "b"]}
