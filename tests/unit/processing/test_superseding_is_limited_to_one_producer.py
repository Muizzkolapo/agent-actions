"""The two rows a recorded input set must never infer away.

`stored_rows_not_reproduced` reads the run's input to decide that a stored row's
producer no longer exists, and drops the row when it does. That reading is sound
for exactly one shape — a row naming a single producer, which on the batch path
means a minted row whose producer is its only input. Two neighbouring shapes look
like they should follow the same rule and must not:

- a row naming *several* producers holds what each of them gave it, so its content
  is not any one producer's to replace;
- a row naming *none* carries its own input's identity, and a run that did not take
  that identity merely narrowed past it.

Both exclusions are load-bearing and both delete rows if removed. Every other test
of this function passes no input set at all, which is the one state where the
inference is unreachable — so without these the widened rule passes a green suite.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.processing.disposition_gate import stored_rows_not_reproduced
from agent_actions.record.state import RecordState

PROCESSED = RecordState.PROCESSED.value


def _stored(guid: str, *, producers: list[str] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"source_guid": guid, "answer": f"answer-{guid}", "_state": PROCESSED}
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


class TestARowNamingSeveralProducersIsNeverInferredAway:
    def test_it_is_carried_even_when_no_producer_is_an_input(self):
        """A many-to-one row holds each input's content; no single one replaces it."""
        stored = [_stored("m1", producers=["i1", "i2"])]
        produced = [_stored("n1", producers=["i9"])]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"i9"})

        assert carry == {"m1"}, (
            "a row naming several producers was inferred away from the input set"
        )

    def test_it_is_carried_when_only_some_of_its_producers_are_inputs(self):
        stored = [_stored("m1", producers=["i1", "i2"])]
        produced = [_stored("n1", producers=["i1"])]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"i1"})

        assert carry == {"m1"}, "dropping it would take the untouched input's content with it"


class TestARowNamingNoProducerIsNotJudgedByTheInputSet:
    def test_it_is_carried_when_its_own_identity_is_not_an_input(self):
        """Its guid is an input's own, so absence from this run's input is a narrowing."""
        stored = [_stored("i1")]
        produced = [_stored("i2")]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"i2"})

        assert carry == {"i1"}, (
            "a row carrying its input's identity was inferred away from the input set"
        )

    def test_it_is_still_replaced_when_the_run_answered_for_it(self):
        """The exclusion must not reach the other way and keep a replaced row."""
        stored = [_stored("i1")]
        produced = [_stored("i1")]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"i1"})

        assert carry == set()


class TestTheSingleProducerRuleStillApplies:
    @pytest.mark.parametrize(
        ("batch_inputs", "expected"),
        [
            # The producer is gone: the row it minted has been replaced.
            ({"a3"}, set()),
            # The producer is still an input: this run simply did not answer for it.
            ({"a1", "a3"}, {"m1"}),
            # Nothing recorded: no inference at all.
            (set(), {"m1"}),
        ],
    )
    def test_one_producer_is_read_against_the_input(self, batch_inputs, expected):
        stored = [_stored("m1", producers=["a1"])]
        produced = [_stored("n1", producers=["a3"])]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs=batch_inputs)

        assert carry == expected


class TestAGenerationIsOnlyReplacedWhenTheReplacementArrived:
    """Superseding deletes, so it needs the replacement to be in this write."""

    def test_a_run_that_settled_nothing_keeps_every_stored_row(self):
        """Every record came back failed: the generation that would replace them never did."""
        stored = [_stored("b1", producers=["a1"]), _stored("b2", producers=["a2"])]
        failed = [
            {"source_guid": "a3", "error": "provider overloaded", "_state": "failed"},
            {"source_guid": "a4", "error": "provider overloaded", "_state": "failed"},
        ]

        carry = stored_rows_not_reproduced(stored, failed, batch_inputs={"a3", "a4"})

        assert carry == {"b1", "b2"}, "a failed run deleted the answers it could not replace"

    def test_a_run_that_produced_nothing_keeps_every_stored_row(self):
        stored = [_stored("b1", producers=["a1"]), _stored("b2", producers=["a2"])]

        carry = stored_rows_not_reproduced(stored, [], batch_inputs={"a3", "a4"})

        assert carry == {"b1", "b2"}, "an empty write emptied the file"

    def test_a_run_that_answered_only_part_of_its_input_keeps_every_stored_row(self):
        """Half a replacement is not one: which stored row it replaces is unknowable."""
        stored = [_stored("b1", producers=["a1"]), _stored("b2", producers=["a2"])]
        produced = [_stored("n1", producers=["a3"])]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a3", "a4"})

        assert carry == {"b1", "b2"}


class TestOneMissingProducerIsNotAGeneration:
    def test_a_row_whose_producer_alone_went_away_is_carried(self):
        """An upstream guard newly filtering one record must not delete its rows.

        The other producers are still inputs, so nothing was re-minted — one record
        left the input, which is not the same thing as a generation being replaced.
        """
        stored = [
            _stored("x1", producers=["r"]),
            _stored("x2", producers=["s"]),
            _stored("x3", producers=["t"]),
        ]
        produced = [_stored("y2", producers=["s"]), _stored("y3", producers=["t"])]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"s", "t"})

        assert carry == {"x1"}, (
            f"the filtered record's rows were deleted as a stale generation: {carry}"
        )

    def test_the_whole_generation_going_away_is_still_superseded(self):
        """The contrast: no stored producer is an input, so all of them were re-minted."""
        stored = [_stored("x1", producers=["r"]), _stored("x2", producers=["s"])]
        produced = [_stored("y1", producers=["u"]), _stored("y2", producers=["v"])]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u", "v"})

        assert carry == set()


@pytest.mark.xfail(
    reason="An action that mints no identity of its own carries its input's, so below an "
    "expansion its rows name a re-minted upstream child and still accumulate. Closing it "
    "means reading a missing identity as a gone generation, which is exactly what "
    "test_a_minted_row_whose_input_is_gone_is_still_carried forbids — an input that is "
    "merely absent keeps its rows. Needs its own decision, not this rule widened.",
    strict=True,
)
def test_an_action_that_mints_nothing_below_an_expansion_still_accumulates():
    """The known remaining gap, recorded as a defect rather than as behaviour.

    `is_expansion` is `len(structured_items) > 1`, so an action is 1:1 for any input
    it answered with a single row and records no producer for it. Its stored rows then
    carry the previous run's upstream child identity and match nothing.
    """
    stored = [_stored("a1"), _stored("a2")]
    produced = [_stored("a3"), _stored("a4")]

    carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a3", "a4"})

    assert carry == set(), f"the previous generation was carried beside its replacement: {carry}"
