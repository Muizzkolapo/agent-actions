"""The repair warns that it may duplicate rows only for a record that could have made them.

Rows it cannot trace back to an input are carried as untouched. That is a risk of
duplication only for a named record that may own some of them, and a record whose only
stored row is its own failed or skipped one made no other row, so nothing it
regenerates can duplicate one.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.processing.disposition_gate import DispositionGate

ACTION = "roll_up"
PATH = "f.json"


class _Backend:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def read_target_for_rewrite(self, action: str, path: str) -> list[dict]:
        return list(self._rows)


def _row(guid: str, state: str = "processed", parent: str = "ancestor") -> dict:
    return {"source_guid": guid, "parent_source_guid": parent, "_state": state}


# Rows minted below another mint name the first ancestor, which is no input here, so
# the repair cannot place them.
UNPLACED = [_row("u1", parent="elsewhere-1"), _row("u2", parent="elsewhere-2")]


def _carried(rows: list[dict], inputs: list[str], named: set[str], caplog) -> str:
    caplog.set_level(logging.WARNING, logger="agent_actions.processing.disposition_gate")
    gate = DispositionGate(_Backend(rows), repairing=named)
    gate.carried_past_repair(ACTION, PATH, [{"source_guid": g} for g in inputs])
    return caplog.text


class TestNoWarningWhenTheNamedRecordMadeNothingElse:
    @pytest.mark.parametrize("state", ["failed", "exhausted", "cascade_skipped", "guard_skipped"])
    def test_a_record_whose_own_row_answers_nothing(self, caplog, state):
        rows = [_row("i1", state), *UNPLACED]

        text = _carried(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "cannot be attributed" not in text

    def test_every_named_record_is_of_that_kind(self, caplog):
        rows = [_row("i1", "failed"), _row("i2", "exhausted"), *UNPLACED]

        text = _carried(rows, ["i1", "i2", "i3"], {"i1", "i2"}, caplog)

        assert "cannot be attributed" not in text


class TestWarningWhereARecordCouldHaveMadeThem:
    def test_a_record_with_an_answer_stored(self, caplog):
        rows = [_row("i1", "processed"), *UNPLACED]

        text = _carried(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "2 stored row(s) cannot be attributed" in text
        assert "repairing 1 record(s)" in text

    def test_a_record_with_no_stored_row_of_its_own(self, caplog):
        """Nothing says it made none: its rows may be among the ones that cannot be placed."""
        text = _carried(list(UNPLACED), ["i1", "i2"], {"i1"}, caplog)

        assert "cannot be attributed" in text

    def test_one_failed_record_beside_one_with_an_answer_counts_only_the_second(self, caplog):
        rows = [_row("i1", "failed"), _row("i2", "processed"), *UNPLACED]

        text = _carried(rows, ["i1", "i2", "i3"], {"i1", "i2"}, caplog)

        assert "repairing 1 record(s)" in text

    def test_the_message_cites_no_issue_number(self, caplog):
        rows = [_row("i1", "processed"), *UNPLACED]

        text = _carried(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "issue #" not in text


class TestWhatIsCarriedIsUnchanged:
    def test_the_unplaced_rows_are_carried_whether_or_not_it_warns(self, caplog):
        rows = [_row("i1", "failed"), *UNPLACED]
        caplog.set_level(logging.WARNING)
        gate = DispositionGate(_Backend(rows), repairing={"i1"})

        carried = gate.carried_past_repair(
            ACTION, PATH, [{"source_guid": "i1"}, {"source_guid": "i2"}]
        )

        assert carried == {"u1", "u2"}
