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


def _carried(rows: list[dict], inputs: list[str], named: set[str], caplog) -> tuple[set, str]:
    caplog.set_level(logging.WARNING, logger="agent_actions.processing.disposition_gate")
    gate = DispositionGate(_Backend(rows), repairing=named)
    carried = gate.carried_past_repair(ACTION, PATH, [{"source_guid": g} for g in inputs])
    return carried, caplog.text


class TestARowMintedFromNamedRecordsAloneIsTheirs:
    """Its producer list places it whatever its parent names, so the rerun replaces it."""

    def test_it_is_neither_carried_nor_reported(self, caplog):
        rows = [_row("u1", producers=["i1"]), _row("u2", producers=["i2"])]

        carried, text = _carried(rows, ["i1", "i2"], {"i1"}, caplog)

        assert carried == {"u2"}
        assert "cannot be attributed" not in text

    def test_even_when_the_named_records_own_row_is_a_failed_one(self, caplog):
        """Rows it made in an earlier run stand beside its failed row; they go too."""
        rows = [_row("i1", state="failed"), _row("m1", producers=["i1"], parent="elsewhere")]

        carried, text = _carried(rows, ["i1", "i2"], {"i1"}, caplog)

        assert carried == set()
        assert "cannot be attributed" not in text

    def test_a_row_keeping_an_unnamed_inputs_identity_is_carried(self, caplog):
        """A FILE row keeping i2's identity lists only the other input it took (#1438),
        so its list alone would hand it to a repair of i1."""
        carried, _ = _carried([_row("i2", producers=["i1"])], ["i1", "i2"], {"i1"}, caplog)

        assert carried == {"i2"}

    def test_a_row_made_by_a_record_that_is_no_input_here_is_carried(self, caplog):
        carried, _ = _carried([_row("u1", producers=["i9"])], ["i1"], {"i9"}, caplog)

        assert carried == {"u1"}


class TestWarningWhereANamedRecordMayHaveMadeAnUnplacedRow:
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
            _row("u1", producers=["i1", "i2"]),
            _row("u2", producers=["i2"]),
            _row("u3"),
            _row("u4", producers=["i3"]),
        ]

        text = _warning(rows, ["i1", "i2", "i3"], {"i1"}, caplog)

        assert "2 stored row(s) cannot be attributed" in text
        assert "repairing 1 record(s)" in text

    def test_the_message_cites_no_issue_number(self, caplog):
        text = _warning([_row("u1")], ["i1"], {"i1"}, caplog)

        assert "cannot be attributed" in text
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
