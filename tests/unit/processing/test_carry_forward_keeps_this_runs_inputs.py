"""Which stored rows a batch write carries beside what the run produced.

The rule is the online path's: an action's output holds rows for this run's inputs. A
stored row is carried where the input it answered for is one of the run's and the run did
not answer it again; a row whose input is not among them, or whose input the guard
filtered, is left out. Where no input was recorded every other unanswered row is carried,
since nothing is known about the run, and a run in which something failed and nothing was
answered replaces no stored answer and drops nothing of a filtered input's, as online
leaves the file unwritten -- while the action still calls each stored answer answered.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_actions.processing.disposition_gate import (
    every_answer_vouched_for,
    stored_rows_not_reproduced,
)

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

    def test_stored_may_be_a_one_shot_iterable(self):
        stored = iter([_row("a1"), _row("a2")])

        carry = stored_rows_not_reproduced(stored, [_row("a3")], batch_inputs={"a1", "a3"})

        assert carry == {"a1"}

    def test_a_stored_row_carrying_no_identity_is_never_carried(self):
        stored = [{"_state": "processed"}, _row("a1")]

        assert stored_rows_not_reproduced(stored, [], batch_inputs=()) == {"a1"}


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

    def test_one_answer_is_enough_to_leave_it_out(self):
        """The run produced an output, so the file is this run's."""
        stored = [_row("a1")]
        produced = [_row("a3"), _row("a4", state="failed")]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a3", "a4"}) == set()


class TestARowWhoseInputTheGuardFilteredIsLeftOut:
    """A filtered record holds no row, as online writes none for it."""

    def test_though_the_input_is_one_of_the_runs(self):
        stored = [_row("a1"), _row("a2")]
        produced = [_row("a1")]

        carry = stored_rows_not_reproduced(
            stored, produced, batch_inputs={"a1", "a2"}, filtered={"a2"}
        )

        assert carry == set()

    def test_a_minted_row_goes_with_the_filtered_input_it_named(self):
        stored = [_row("m1", ["a1"]), _row("m2", ["a2"]), _row("m3", ["a2"])]

        carry = stored_rows_not_reproduced(stored, [], batch_inputs={"a1", "a2"}, filtered={"a2"})

        assert carry == {"m1"}

    def test_where_no_input_was_recorded(self):
        """A repair records none; online writes no row for a named record its guard filters."""
        stored = [_row("a1"), _row("a2")]

        assert stored_rows_not_reproduced(stored, [], filtered={"a2"}) == {"a1"}

    @pytest.mark.parametrize("state", ["processed", "exhausted", "failed"])
    def test_not_where_the_run_failed_and_answered_nothing(self, state):
        """Online raises before it writes, so what it held for the input stays, answer
        or not, until a run that writes."""
        stored = [_row("a1"), _row("a2", state=state)]
        produced = [_row("a1", state="failed")]

        carry = stored_rows_not_reproduced(
            stored, produced, batch_inputs={"a1", "a2"}, filtered={"a2"}
        )

        assert carry == {"a1", "a2"}


class TestARunThatFailedAndAnsweredNothingReplacesNoAnswer:
    """Online leaves the file unwritten when everything it sent failed, so its answers stand."""

    @pytest.mark.parametrize(
        "produced",
        [[_row("a3", state="failed")], [_row("n1", ["a3"], state="exhausted")]],
        ids=["a_failure", "an_exhausted_row_naming_its_input"],
    )
    def test_a_stored_answer_stands_whichever_input_it_was_for(self, produced):
        stored = [_row("a1"), _row("m1", ["gone"])]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a3"}) == {"a1", "m1"}

    def test_it_stands_over_a_guard_tombstone_when_the_failure_is_another_row(self):
        """One record failed, so the run is refused whole: the tombstone the guard wrote
        over an answered record gives way to the answer, as the failure row would."""
        stored = [_row("a1"), _row("a2")]
        produced = [_row("a1", state="guard_skipped"), _row("p6", state="failed")]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a1", "a2", "p6"})

        assert carry == {"a1", "a2"}

    def test_it_stands_over_the_failure_row_written_under_its_own_identity(self):
        stored = [_row("a1"), _row("a2")]
        produced = [_row("a1", state="failed"), _row("a2", state="exhausted")]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a1", "a2"})

        assert carry == {"a1", "a2"}

    @pytest.mark.parametrize(
        "produced",
        [[], [_row("a3", state="guard_skipped")], [_row("a3", state="cascade_skipped")]],
        ids=["nothing_produced", "a_guard_tombstone", "a_cascade_skip"],
    )
    def test_without_a_failure_the_file_is_this_runs_and_follows_its_inputs(self, produced):
        """Online writes then, with nothing for a record that has left."""
        stored = [_row("a1"), _row("m1", ["gone"])]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a3"}) == set()

    def test_a_tombstone_still_replaces_the_answer_under_its_identity(self):
        """No failure, so no refusal: the guard's row is this run's row for that input."""
        stored = [_row("a1"), _row("a2")]
        produced = [_row("a1", state="guard_skipped")]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a1", "a2"})

        assert carry == {"a2"}

    @pytest.mark.parametrize("state", ["failed", "exhausted", "guard_skipped", "cascade_skipped"])
    def test_a_stored_row_that_is_no_answer_still_goes_with_its_input(self, state):
        """Kept, each such run over inputs minted again would add its rows beside the last."""
        stored = [_row("a1", state=state), _row("a3", state=state)]
        produced = [_row("a4", state="failed")]

        carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"a3", "a4"})

        assert carry == {"a3"}

    def test_a_row_the_run_wrote_again_is_still_replaced(self):
        stored = [_row("a3", state="failed"), _row("a1")]
        produced = [_row("a3", state="failed")]

        assert stored_rows_not_reproduced(stored, produced, batch_inputs={"a3"}) == {"a1"}


class TestOnlyAnAnswerTheActionStillCallsAnsweredStands:
    """A reset clears every disposition and leaves the stored rows for the re-run to
    replace, so an answer it took back would be served as one to the config it replaced."""

    def test_every_stored_answer_still_answered_stands(self):
        stored = [_row("a1"), _row("m1", ["a2"])]
        produced = [_row("a1", state="failed")]

        carry = stored_rows_not_reproduced(
            stored, produced, batch_inputs={"a1"}, still_answered=lambda: {"a1", "a2"}
        )

        assert carry == {"a1", "m1"}

    @pytest.mark.parametrize(
        ("inputs", "produced"),
        [
            ({"a1", "a2"}, [_row("a1", state="failed"), _row("a2", state="exhausted")]),
            ({"a3"}, [_row("a3", state="failed")]),
        ],
        ids=["the_same_inputs", "inputs_minted_again"],
    )
    def test_after_a_reset_the_file_follows_its_inputs_as_one_that_answered_would(
        self, inputs, produced
    ):
        stored = [_row("a1"), _row("a2")]

        carry = stored_rows_not_reproduced(
            stored, produced, batch_inputs=inputs, still_answered=lambda: set()
        )

        assert carry == set()

    def test_a_failed_input_keeps_none_of_the_rows_it_minted_once_they_are_taken_back(self):
        """Online writes only the failure for it, and carries what the gate still calls
        answered: here the input the run did not send."""
        stored = [_row("m1", ["a1"]), _row("m2", ["a2"]), _row("m3", ["a3"])]
        produced = [_row("a1", state="failed"), _row("a2", state="exhausted")]

        carry = stored_rows_not_reproduced(
            stored, produced, batch_inputs={"a1", "a2", "a3"}, still_answered=lambda: {"a3"}
        )

        assert carry == {"m3"}

    def test_one_answer_taken_back_is_enough_to_write_the_file(self):
        """Online's choice is the file's, not the row's: it writes the file or leaves it."""
        stored = [_row("a1"), _row("a2")]
        produced = [_row("a1", state="failed"), _row("a2", state="failed")]

        carry = stored_rows_not_reproduced(
            stored, produced, batch_inputs={"a1", "a2"}, still_answered=lambda: {"a2"}
        )

        assert carry == set()

    def test_the_dispositions_are_not_read_for_a_run_that_answered_something(self):
        def unread() -> set[str]:
            raise AssertionError("read the dispositions")

        stored_rows_not_reproduced(
            [_row("a1")], [_row("a1"), _row("a2", state="failed")], still_answered=unread
        )


class TestEveryAnswerVouchedFor:
    def test_by_the_identity_it_carries(self):
        assert every_answer_vouched_for([_row("a1")], {"a1"})

    def test_by_an_input_it_names_as_producer(self):
        assert every_answer_vouched_for([_row("m1", ["a1", "a2"])], {"a2"})

    def test_not_an_answer_whose_record_holds_no_success(self):
        assert not every_answer_vouched_for([_row("a1"), _row("a2")], {"a1"})

    @pytest.mark.parametrize("state", ["failed", "exhausted", "guard_skipped", "cascade_skipped"])
    def test_a_row_that_is_no_answer_needs_nothing_to_vouch_for_it(self, state):
        assert every_answer_vouched_for([_row("a1", state=state)], set())

    def test_nothing_stored_needs_nothing(self):
        assert every_answer_vouched_for([], set())


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

    @pytest.mark.parametrize("order", [("gone", "here"), ("here", "gone")])
    def test_an_identity_still_carried_through_another_row_is_not_counted(self, caplog, order):
        stored = [_row("g", [producer]) for producer in order]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(
                stored, [_row("n", ["new"])], batch_inputs={"here", "new"}
            )

        assert carry == {"g"}
        assert _gate_records(caplog) == []

    def test_rows_of_an_input_the_guard_filtered_are_counted_on_a_line_of_their_own(self, caplog):
        """Its input is still one of the run's, so the line for inputs that left does not
        count it."""
        stored = [_row("a1"), _row("a2"), _row("m2", ["a2"]), _row("m1", ["c1"])]
        produced = [_row("a1")]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(
                stored, produced, batch_inputs={"a1", "a2"}, filtered={"a2", "a9"}
            )

        assert carry == set()
        records = _gate_records(caplog)
        assert [r.levelno for r in records] == [logging.INFO, logging.INFO]
        messages = [r.getMessage() for r in records]
        (filtered,) = [m for m in messages if "guard filtered" in m]
        assert filtered.startswith("2 stored row(s) not carried forward"), filtered
        assert "the 2 this run's guard filtered" in filtered, filtered
        (left,) = [m for m in messages if "guard filtered" not in m]
        assert left.startswith("1 stored row(s) not carried forward"), left

    def test_nothing_is_logged_for_a_filtered_input_in_a_run_that_keeps_its_rows(self, caplog):
        stored = [_row("a1"), _row("a2")]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            stored_rows_not_reproduced(
                stored, [_row("a1", state="failed")], batch_inputs={"a1", "a2"}, filtered={"a2"}
            )

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
