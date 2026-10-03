"""Carry-forward reads what upstream still holds, where the run recorded it.

A stored row's own identity cannot tell an upstream action minting its children again from
a record that left the input, or from one a guard filtered: all are "an identity no input
names". Two recordings can: the upstream pool as it stood before any guard drop, and for
each identity the staged record it descends from (`parent_source_guid` where a row has
one, else its own identity).
"""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.processing.disposition_gate import stored_rows_not_reproduced

GATE_LOGGER = "agent_actions.processing.disposition_gate"


def _row(
    guid: str,
    *,
    parent: str | None = None,
    producers: list[str] | None = None,
    state: str = "processed",
) -> dict[str, Any]:
    row: dict[str, Any] = {"source_guid": guid, "_state": state}
    if parent is not None:
        row["parent_source_guid"] = parent
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


def _carry(
    stored, produced, ancestors: dict[str, str], *, filtered: dict[str, str] | None = None
) -> set[str]:
    """*filtered* names the upstream records a guard dropped before the run took its input."""
    return stored_rows_not_reproduced(
        stored,
        produced,
        batch_inputs=set(ancestors),
        input_ancestors=ancestors,
        upstream_pool={**ancestors, **(filtered or {})},
    )


class TestARemintedGenerationIsReplaced:
    def test_a_one_to_one_action_below_an_expansion_does_not_accumulate(self):
        """#1155: the upstream children are a3, a4 this run; a1, a2 no longer exist."""
        stored = [_row("a1", parent="S"), _row("a2", parent="S")]
        produced = [_row("a3", parent="S"), _row("a4", parent="S")]

        assert _carry(stored, produced, {"a3": "S", "a4": "S"}) == set()

    def test_a_stable_row_does_not_keep_a_replaced_mint_generation_beside_it(self):
        """The shape that broke widening one flag over the whole stored set."""
        stored = [
            _row("x1", parent="P", producers=["c1"]),
            _row("x2", parent="P", producers=["c1"]),
            _row("s1"),
        ]
        produced = [
            _row("y1", parent="P", producers=["c3"]),
            _row("y2", parent="P", producers=["c3"]),
            _row("s1"),
        ]

        assert _carry(stored, produced, {"c3": "P", "s1": "s1"}) == set()

    def test_a_failed_stored_row_of_a_replaced_generation_goes_with_it(self):
        stored = [_row("a1", parent="S", state="failed"), _row("a2", parent="S")]
        produced = [_row("a3", parent="S"), _row("a4", parent="S")]

        assert _carry(stored, produced, {"a3": "S", "a4": "S"}) == set()

    def test_only_the_record_that_was_reminted_is_replaced(self):
        stored = [_row("a1", parent="S"), _row("b1", parent="T")]
        produced = [_row("a2", parent="S"), _row("b2", parent="T", state="failed")]

        assert _carry(stored, produced, {"a2": "S", "b2": "T"}) == {"b1"}


class TestARecordThatLeftTheInputKeepsItsRows:
    def test_a_guard_filtering_one_record_keeps_its_answer(self):
        """The shape that broke judging each class of row separately."""
        stored = [
            _row("m1a", parent="P1", producers=["P1"]),
            _row("m1b", parent="P1", producers=["P1"]),
            _row("m2a", parent="P2", producers=["P2"]),
            _row("P3"),
        ]
        produced = [
            _row("n1a", parent="P1", producers=["P1"]),
            _row("n1b", parent="P1", producers=["P1"]),
            _row("n2a", parent="P2", producers=["P2"]),
        ]

        carry = _carry(stored, produced, {"P1": "P1", "P2": "P2"}, filtered={"P3": "P3"})

        assert carry == {"P3"}

    def test_a_new_batch_of_records_keeps_the_previous_batchs_mints(self):
        """#1206: nothing this run took came from r1 or r2."""
        stored = [
            _row("m1", parent="r1", producers=["r1"]),
            _row("m2", parent="r2", producers=["r2"]),
        ]
        produced = [_row("m3", parent="r3", producers=["r3"])]

        assert _carry(stored, produced, {"r3": "r3"}) == {"m1", "m2"}

    def test_a_new_batch_of_records_keeps_the_previous_batchs_answers(self, caplog):
        stored = [_row("r1"), _row("r2")]
        produced = [_row("r3")]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = _carry(stored, produced, {"r3": "r3"})

        assert carry == {"r1", "r2"}
        assert [r for r in caplog.records if r.name == GATE_LOGGER] == []

    def test_one_stable_sibling_filtered_keeps_its_row(self):
        """Siblings whose identities did not change were not re-minted, so one of them
        missing from the input is a record that left, not a generation replaced."""
        stored = [_row("a1", parent="S"), _row("a2", parent="S")]
        produced = [_row("a1", parent="S")]

        assert _carry(stored, produced, {"a1": "S"}, filtered={"a2": "S"}) == {"a2"}

    def test_a_sibling_newly_admitted_does_not_condemn_the_one_newly_filtered(self):
        """c2 is not a re-mint of c1: c1 still exists upstream, a guard dropped it."""
        stored = [_row("c1", parent="S")]
        produced = [_row("c2", parent="S")]

        assert _carry(stored, produced, {"c2": "S"}, filtered={"c1": "S"}) == {"c1"}


class TestMixedAndLeftoverShapes:
    def test_a_stable_sibling_of_the_same_record_does_not_pin_a_replaced_generation(self):
        stored = [
            _row("x1", parent="P", producers=["c1"]),
            _row("x2", parent="P", producers=["c1"]),
            _row("s1", parent="P"),
        ]
        produced = [
            _row("y1", parent="P", producers=["c3"]),
            _row("y2", parent="P", producers=["c3"]),
            _row("s1", parent="P"),
        ]

        assert _carry(stored, produced, {"s1": "P", "c3": "P"}) == set()

    def test_rows_left_by_an_earlier_partial_run_go_once_the_record_settles(self):
        stored = [_row(g, parent="S") for g in ("a3", "a4", "a1", "a2")]
        produced = [_row("a3", parent="S"), _row("a4", parent="S")]

        assert _carry(stored, produced, {"a3": "S", "a4": "S"}) == set()

    def test_a_guard_skipped_input_settles_its_record(self):
        """A skip is a healthy outcome: the record is settled though one input is unanswered."""
        stored = [_row("a1", parent="S"), _row("a2", parent="S", state="guard_skipped")]
        produced = [_row("a3", parent="S"), _row("a4", parent="S", state="guard_skipped")]

        assert _carry(stored, produced, {"a3": "S", "a4": "S"}) == set()


class TestNothingIsInferredShortOfTheWholeRecord:
    def test_no_recorded_upstream_pool_infers_nothing(self):
        """Without the pool nothing is known to be gone upstream."""
        stored = [_row("a1", parent="S"), _row("a2", parent="S")]
        produced = [_row("a3", parent="S"), _row("a4", parent="S")]
        ancestors = {"a3": "S", "a4": "S"}

        carry = stored_rows_not_reproduced(
            stored, produced, batch_inputs=set(ancestors), input_ancestors=ancestors
        )

        assert carry == {"a1", "a2"}

    def test_a_record_only_partly_answered_keeps_its_stored_rows(self):
        stored = [_row("a1", parent="S"), _row("a2", parent="S")]
        produced = [_row("a3", parent="S"), _row("a4", parent="S", state="failed")]

        assert _carry(stored, produced, {"a3": "S", "a4": "S"}) == {"a1", "a2"}

    def test_a_row_merging_several_inputs_is_never_replaced(self):
        stored = [_row("m", parent="S", producers=["c1", "c2"]), _row("a1", parent="S")]
        produced = [_row("a3", parent="S")]

        assert _carry(stored, produced, {"a3": "S"}) == {"m"}

    def test_a_run_that_recorded_no_inputs_infers_nothing(self):
        stored = [_row("a1", parent="S")]
        produced = [_row("a3", parent="S")]

        assert _carry(stored, produced, {}) == {"a1"}


class TestARunRecordedBeforeAncestorsBehavesAsItDid:
    def test_the_identity_only_rule_still_applies_without_ancestors(self):
        stored = [
            _row("m1", parent="r1", producers=["r1"]),
            _row("m2", parent="r2", producers=["r2"]),
        ]
        produced = [_row("m3", parent="r3", producers=["r3"])]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"r3"}) == set()


class TestTheDropIsReported:
    def test_one_info_record_names_the_rows_and_the_records(self, caplog):
        stored = [_row("a1", parent="S"), _row("a2", parent="S"), _row("b1", parent="T")]
        produced = [_row("a3", parent="S"), _row("b2", parent="T")]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = _carry(stored, produced, {"a3": "S", "b2": "T"})

        assert carry == set()
        records = [r for r in caplog.records if r.name == GATE_LOGGER]
        assert len(records) == 1, [(r.levelname, r.getMessage()) for r in records]
        assert records[0].levelno == logging.INFO
        message = records[0].getMessage()
        assert message.startswith("3 stored row(s) dropped, not carried forward"), message
        assert "2 staged record(s)" in message, message
