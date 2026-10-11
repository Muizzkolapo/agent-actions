"""Edges of the repair's duplication warning that the first tests left open.

The rule: a row the repair cannot place is reported when it lists a named record among
its producers, or lists none. These pin the places a plausible wrong version differs.
"""

from __future__ import annotations

import logging

from agent_actions.processing.disposition_gate import DispositionGate

ACTION = "roll_up"
PATH = "f.json"


class _Backend:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def read_target_for_rewrite(self, action: str, path: str) -> list[dict]:
        return list(self._rows)


def _row(guid: str, producers: list[str] | None = None, state: str = "processed") -> dict:
    row = {"source_guid": guid, "parent_source_guid": f"ancestor-of-{guid}", "_state": state}
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


def _run(rows: list[dict], inputs: list[str], named: set[str], caplog):
    caplog.set_level(logging.WARNING, logger="agent_actions.processing.disposition_gate")
    gate = DispositionGate(_Backend(rows), repairing=named)
    carried = gate.carried_past_repair(ACTION, PATH, [{"source_guid": g} for g in inputs])
    return carried, caplog.text


class TestAProducerListedAnywhereInTheRow:
    def test_the_named_record_is_not_the_first_producer(self, caplog):
        """A many-to-one row lists every input that fed it, in no order that matters."""
        _, text = _run([_row("u1", ["i2", "i1"])], ["i1", "i2"], {"i1"}, caplog)

        assert "1 stored row(s) cannot be attributed" in text


class TestTheCountIsRows:
    def test_two_rows_made_by_the_one_named_record_count_as_two(self, caplog):
        rows = [_row("u1", ["i1"]), _row("u2", ["i1"]), _row("u3", ["i2"])]

        _, text = _run(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "2 stored row(s) cannot be attributed" in text
        assert "repairing 1 record(s)" in text


class TestWhatIsCarried:
    def test_the_failed_row_of_an_input_that_is_not_named_is_carried(self, caplog):
        """Another record's failure is the only evidence of it; a repair of a neighbour
        must not drop it."""
        rows = [_row("i1", state="failed"), _row("i2", state="failed"), _row("u1", ["i2"])]

        carried, _ = _run(rows, ["i1", "i2"], {"i1"}, caplog)

        assert carried == {"i2", "u1"}


class TestAWarningThatFiresCitesNothingClosed:
    def test_it_is_emitted_and_names_no_issue_number(self, caplog):
        _, text = _run([_row("u1", ["i1"])], ["i1"], {"i1"}, caplog)

        assert "cannot be attributed" in text
        assert "issue #" not in text
