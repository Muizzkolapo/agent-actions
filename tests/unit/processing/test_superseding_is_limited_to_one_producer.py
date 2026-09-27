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
