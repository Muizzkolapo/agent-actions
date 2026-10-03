"""Which stored rows a batch write carries beside what the run produced.

The rule is the online path's: an action's output holds rows for this run's inputs. A
stored row is carried where the input it answered for is one of the run's and the run did
not answer it again; a row whose input is not among them is left out. Only where no input
was recorded is every unanswered row carried, since nothing is known about the run.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_actions.processing.disposition_gate import stored_rows_not_reproduced

GATE_LOGGER = "agent_actions.processing.disposition_gate"


def _row(guid: str, producers: list[str] | None = None, state: str = "processed") -> dict[str, Any]:
    row: dict[str, Any] = {"source_guid": guid, "_state": state}
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


def _gate_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == GATE_LOGGER]


class TestARowWhoseInputIsInTheRunIsCarried:
    def test_an_input_the_run_left_unanswered_keeps_its_row(self):
        """The gate carried it, or a limit left it out: it is still one of the inputs."""
        stored = [_row("a1"), _row("a2")]
        produced = [_row("a2")]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a1", "a2"}) == {"a1"}

    def test_a_minted_row_is_kept_through_the_input_it_names(self):
        stored = [_row("m1", ["a1"]), _row("m2", ["a1"]), _row("m3", ["a2"])]
        produced = [_row("n1", ["a2"])]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a1", "a2"})

        assert carry == {"m1", "m2"}

    @pytest.mark.parametrize("state", ["failed", "exhausted", "cascade_skipped"])
    def test_an_input_that_did_not_settle_keeps_the_row_it_had(self, state):
        """Only a processed row answers for its input. The unsettled one is written under
        a minted identity here, so the stored answer is not rewritten either."""
        stored = [_row("m1", ["a1"])]
        produced = [_row("n1", ["a1"], state=state)]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a1"}) == {"m1"}

    def test_a_run_that_produced_nothing_keeps_the_rows_of_its_inputs(self):
        stored = [_row("a1"), _row("m2", ["a2"])]

        assert stored_rows_not_reproduced(stored, [], batch_inputs={"a1", "a2"}) == {"a1", "m2"}


class TestARowWhoseInputIsNotInTheRunIsLeftOut:
    def test_an_action_below_an_expansion_does_not_keep_the_previous_generation(self):
        """#1155: the upstream children are a3 and a4 this run; a1 and a2 are no input."""
        stored = [_row("a1"), _row("a2")]
        produced = [_row("a3"), _row("a4")]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a3", "a4"}) == set()

    def test_a_minted_row_goes_with_the_input_it_named(self):
        stored = [_row("m1", ["c1"]), _row("m2", ["c2"])]
        produced = [_row("n1", ["c2"])]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"c2"}) == set()

    def test_one_input_leaving_takes_only_its_own_row(self):
        stored = [_row("a1"), _row("a2"), _row("a3")]
        produced = [_row("a1")]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a1", "a2"})

        assert carry == {"a2"}

    def test_it_is_left_out_whether_or_not_the_run_settled(self):
        """As online: a run that fails over new inputs still writes only those inputs."""
        stored = [_row("a1")]
        produced = [_row("a3", state="failed")]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a3"}) == set()


class TestARowAnsweredAgainIsReplaced:
    def test_by_the_identity_it_carries(self):
        stored = [_row("a1")]
        produced = [_row("a1")]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a1"}) == set()

    def test_by_the_producer_it_names(self):
        stored = [_row("m1", ["a1"])]
        produced = [_row("n1", ["a1"])]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a1"}) == set()

    def test_a_row_rewritten_under_its_identity_is_not_carried_beside_itself(self):
        """Whatever the new row's state: carried too, the identity is stored twice."""
        stored = [_row("a1"), _row("m", ["c1", "c2"])]
        produced = [_row("a1", state="failed"), _row("m", ["c1", "c2"])]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a1"}) == set()


class TestARowMergingSeveralInputsIsAlwaysCarried:
    def test_when_none_of_its_producers_is_an_input(self):
        """It holds what each input gave it, so no one input accounts for it."""
        stored = [_row("m1", ["i1", "i2"])]
        produced = [_row("n1", ["i9"])]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"i9"}) == {"m1"}

    def test_when_one_of_its_producers_was_answered_again(self):
        stored = [_row("m1", ["i1", "i2"])]
        produced = [_row("n1", ["i1"])]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"i1"}) == {"m1"}


class TestWithNoInputRecordedEveryUnansweredRowIsCarried:
    @pytest.mark.parametrize("batch_inputs", [(), set(), []])
    def test_nothing_is_left_out(self, batch_inputs):
        """A batch submitted before inputs were recorded, or one that recorded none."""
        stored = [_row("a1"), _row("m1", ["c1"])]
        produced = [_row("a3")]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs=batch_inputs)

        assert carry == {"a1", "m1"}

    def test_stored_may_be_a_one_shot_iterable(self):
        stored = iter([_row("a1"), _row("a2")])

        assert stored_rows_not_reproduced(stored, [], batch_inputs={"a1"}) == {"a1"}


class TestWhatIsLeftOutIsReported:
    def test_one_info_record_names_the_rows_and_the_inputs(self, caplog):
        stored = [_row("a1"), _row("a2"), _row("m1", ["c1"]), _row("keep")]
        produced = [_row("a3")]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a3", "keep"})

        assert carry == {"keep"}
        records = _gate_records(caplog)
        assert len(records) == 1, [(r.levelname, r.getMessage()) for r in records]
        assert records[0].levelno == logging.INFO
        message = records[0].getMessage()
        assert message.startswith("3 stored row(s) not carried forward"), message
        assert "the 2 this run took" in message, message

    def test_two_rows_sharing_an_identity_count_once(self, caplog):
        stored = [_row("g", ["c1"]), _row("g", ["c2"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            stored_rows_not_reproduced(stored, [_row("n", ["u"])], batch_inputs={"u"})

        (record,) = _gate_records(caplog)
        assert record.getMessage().startswith("1 stored row(s)"), record.getMessage()

    def test_an_identity_still_carried_through_another_row_is_not_counted(self, caplog):
        stored = [_row("g", ["gone"]), _row("g", ["here"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, [], batch_inputs={"here"})

        assert carry == {"g"}
        assert _gate_records(caplog) == []

    @pytest.mark.parametrize(
        ("produced", "batch_inputs"),
        [
            ([_row("a1"), _row("a2")], {"a1", "a2"}),
            ([_row("a2")], {"a1", "a2"}),
            ([_row("a3")], ()),
        ],
        ids=["all_answered_again", "one_carried", "no_inputs_recorded"],
    )
    def test_nothing_is_logged_when_nothing_is_left_out(self, caplog, produced, batch_inputs):
        stored = [_row("a1"), _row("a2")]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            stored_rows_not_reproduced(stored, produced, batch_inputs=batch_inputs)

        assert _gate_records(caplog) == []
