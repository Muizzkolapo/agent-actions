"""The repair warns that it may duplicate rows only where a named record may have made them.

Rows it cannot trace back to an input are carried as untouched. That risks duplication
only when a record the repair names may be the one that made them. A row lists the
inputs that produced it, so a row made by other inputs is no risk however the named
record's own row stands, and a row that lists a named record is one even when the named
record's own row is a failed one stored beside it.
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


def _row(
    guid: str,
    *,
    producers: list[str] | None = None,
    state: str = "processed",
    parent: str | None = None,
) -> dict:
    row = {"source_guid": guid, "parent_source_guid": parent or f"ancestor-of-{guid}"}
    row["_state"] = state
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


def _warning(rows: list[dict], inputs: list[str], named: set[str], caplog) -> str:
    caplog.set_level(logging.WARNING, logger="agent_actions.processing.disposition_gate")
    gate = DispositionGate(_Backend(rows), repairing=named)
    gate.carried_past_repair(ACTION, PATH, [{"source_guid": g} for g in inputs])
    return caplog.text


class TestNoWarningWhenOtherInputsMadeTheUnplacedRows:
    def test_rows_made_by_inputs_the_repair_did_not_name(self, caplog):
        rows = [_row("u1", producers=["i2"]), _row("u2", producers=["i3"])]

        text = _warning(rows, ["i1", "i2", "i3"], {"i1"}, caplog)

        assert "cannot be attributed" not in text

    def test_the_named_records_own_row_is_failed(self, caplog):
        """The retry replaces that row; the rows beside it are other records'."""
        rows = [
            _row("i1", state="failed"),
            _row("u1", producers=["i2"]),
            _row("u2", producers=["i3"]),
        ]

        text = _warning(rows, ["i1", "i2", "i3"], {"i1"}, caplog)

        assert "cannot be attributed" not in text

    def test_the_named_record_has_an_answer_stored(self, caplog):
        rows = [_row("i1"), _row("u1", producers=["i2"])]

        text = _warning(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "cannot be attributed" not in text


class TestWarningWhereANamedRecordMayHaveMadeAnUnplacedRow:
    def test_a_row_lists_the_named_record_as_its_producer(self, caplog):
        rows = [_row("u1", producers=["i1"]), _row("u2", producers=["i2"])]

        text = _warning(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "1 stored row(s) cannot be attributed" in text

    def test_even_when_the_named_records_own_row_is_a_failed_one(self, caplog):
        """A failed row of its own does not mean it made no other: rows it made in an
        earlier run can stand beside it, and regenerating it adds a second set."""
        rows = [_row("i1", state="failed"), _row("m1", producers=["i1"], parent="elsewhere")]

        text = _warning(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "1 stored row(s) cannot be attributed" in text

    def test_among_several_producers(self, caplog):
        rows = [_row("u1", producers=["i1", "i2"])]

        text = _warning(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "cannot be attributed" in text

    def test_a_row_that_names_no_producer(self, caplog):
        """Nothing says who made it, so a named record may have."""
        rows = [_row("u1"), _row("u2", producers=["i2"])]

        text = _warning(rows, ["i1", "i2"], {"i1"}, caplog)

        assert "1 stored row(s) cannot be attributed" in text

    def test_only_the_rows_a_named_record_may_have_made_are_counted(self, caplog):
        rows = [
            _row("u1", producers=["i1"]),
            _row("u2", producers=["i2"]),
            _row("u3"),
            _row("u4", producers=["i3"]),
        ]

        text = _warning(rows, ["i1", "i2", "i3"], {"i1"}, caplog)

        assert "2 stored row(s) cannot be attributed" in text
        assert "repairing 1 record(s)" in text

    def test_the_message_cites_no_issue_number(self, caplog):
        text = _warning([_row("u1", producers=["i1"])], ["i1"], {"i1"}, caplog)

        assert "issue #" not in text


class TestWhatIsCarriedIsUnchanged:
    def test_every_unplaced_row_is_carried_whether_or_not_it_warns(self, caplog):
        rows = [
            _row("i1", state="failed"),
            _row("u1", producers=["i2"]),
            _row("u2", producers=["i3"]),
            _row("u3", producers=["i2"], state="failed"),
        ]
        caplog.set_level(logging.WARNING)
        gate = DispositionGate(_Backend(rows), repairing={"i1"})

        inputs = [{"source_guid": g} for g in ("i1", "i2", "i3")]
        carried = gate.carried_past_repair(ACTION, PATH, inputs)

        assert carried == {"u1", "u2", "u3"}
