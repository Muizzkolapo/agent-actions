"""An output that grows every run says so, instead of growing silently.

Below an expansion, an action that answers an input with a single row records no
producer — `is_expansion` is `len(structured_items) > 1` — so its stored rows carry the
previous run's upstream child identity, match nothing this run produced, and are kept
beside their replacements. Two extra rows per run, with no signal.

This does not stop the accumulation. Inferring that an absent identity is a replaced
generation is exactly what #1151 forbids: an input that is merely absent — unstaged,
filtered upstream, dropped by a limit — looks identical, and deleting its rows would be
data loss. `test_a_minted_row_whose_input_is_gone_is_still_carried` pins that refusal.

So the row is still carried, and the condition is named. Same answer
`carried_past_repair` already gives for its own unresolvable case (#1022).
"""

import logging

from agent_actions.processing.disposition_gate import stored_rows_not_reproduced
from agent_actions.record.state import RecordState


def _row(guid: str, producers: list[str] | None = None) -> dict:
    row: dict = {"source_guid": guid, "_state": RecordState.PROCESSED.value}
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


class TestTheAccumulatingShapeIsNamed:
    def test_a_producerless_row_no_input_names_is_reported(self, caplog):
        """The issue's shape: A(expand) -> B(1:1), nothing changed between runs."""
        with caplog.at_level(logging.WARNING):
            carry = stored_rows_not_reproduced(
                [_row("a1"), _row("a2")], [_row("a3"), _row("a4")], batch_inputs={"a3", "a4"}
            )

        assert carry == {"a1", "a2"}, "still carried — inferring otherwise would delete rows"
        assert any("grows every run" in r.getMessage() for r in caplog.records), [
            r.getMessage() for r in caplog.records
        ]

    def test_the_report_counts_the_rows(self, caplog):
        with caplog.at_level(logging.WARNING):
            stored_rows_not_reproduced([_row("a1"), _row("a2")], [_row("a3")], batch_inputs={"a3"})

        assert any("2 stored row(s)" in r.getMessage() for r in caplog.records)

    def test_it_names_the_issue_so_the_condition_can_be_looked_up(self, caplog):
        with caplog.at_level(logging.WARNING):
            stored_rows_not_reproduced([_row("a1")], [_row("a2")], batch_inputs={"a2"})

        assert any("#1155" in r.getMessage() for r in caplog.records)


class TestTheOrdinaryCasesStaySilent:
    """A warning on every run would be worse than none."""

    def test_a_row_whose_input_is_still_present_is_not_reported(self, caplog):
        """Carried because the run did not answer for it — ordinary, not accumulation."""
        with caplog.at_level(logging.WARNING):
            carry = stored_rows_not_reproduced(
                [_row("a1")], [_row("a2")], batch_inputs={"a1", "a2"}
            )

        assert carry == {"a1"}
        assert not [r for r in caplog.records if "grows every run" in r.getMessage()]

    def test_a_row_with_producers_is_not_reported(self, caplog):
        """It has something to attribute it by, which is the case #1151 closed.

        Two producers, not one: a single-producer row is superseded before the report is
        reached, so it cannot tell whether the producer check does anything. A merge row
        naming several is never inferred away, so it IS carried — and must stay silent.
        """
        with caplog.at_level(logging.WARNING):
            carry = stored_rows_not_reproduced(
                [_row("m1", producers=["p", "q"])],
                [_row("y1", producers=["here"])],
                batch_inputs={"here"},
            )

        assert carry == {"m1"}, "a merge row is carried, so the report branch is reached"
        assert not [r for r in caplog.records if "grows every run" in r.getMessage()]

    def test_a_reproduced_row_is_not_reported(self, caplog):
        with caplog.at_level(logging.WARNING):
            carry = stored_rows_not_reproduced([_row("a1")], [_row("a1")], batch_inputs={"a1"})

        assert carry == set()
        assert not [r for r in caplog.records if "grows every run" in r.getMessage()]

    def test_no_recorded_input_reports_nothing(self, caplog):
        """Without batch_inputs nothing is knowable, so nothing is claimed."""
        with caplog.at_level(logging.WARNING):
            stored_rows_not_reproduced([_row("a1")], [_row("a2")])

        assert not [r for r in caplog.records if "grows every run" in r.getMessage()]
