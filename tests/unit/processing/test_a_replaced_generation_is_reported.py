"""Stored rows dropped as a replaced generation are reported, not dropped silently.

When no stored single-producer row names an input of this run, and the run answered
every input, `stored_rows_not_reproduced` reads those rows as a generation the upstream
action re-minted and does not carry them. Whether that reading is right is held (#1155);
these tests pin only that the drop is reported, once, at INFO, with the counts that
decided it. Every test also pins the carry set, so the report cannot move it.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_actions.processing.disposition_gate import stored_rows_not_reproduced
from agent_actions.record.state import RecordState

GATE_LOGGER = "agent_actions.processing.disposition_gate"
DROP_PHRASE = "dropped, not carried forward"


def _row(
    guid: str, producers: list[str] | None = None, state: str = RecordState.PROCESSED.value
) -> dict[str, Any]:
    row: dict[str, Any] = {"source_guid": guid, "_state": state}
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


def _gate_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == GATE_LOGGER]


def _drop_reports(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in _gate_records(caplog) if DROP_PHRASE in r.getMessage()]


def _the_drop_report(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    reports = _drop_reports(caplog)
    assert len(reports) == 1, [(r.levelname, r.getMessage()) for r in _gate_records(caplog)]
    assert reports[0].levelno == logging.INFO, reports[0].levelname
    return reports[0]


class TestAReplacedGenerationIsReported:
    def test_the_issue_repro_emits_one_info_record_naming_two_dropped_rows(self, caplog):
        stored = [_row("m1", ["r1"]), _row("m2", ["r2"])]
        produced = [_row("m3", ["r3"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"r3"})

        assert carry == set()
        records = _gate_records(caplog)
        assert len(records) == 1, [(r.levelname, r.getMessage()) for r in records]
        assert records[0].levelno == logging.INFO
        message = records[0].getMessage()
        assert message.startswith("2 stored row(s) dropped, not carried forward"), message

    def test_the_message_names_the_counts_that_decided_it(self, caplog):
        """Three rows from two records, against one input: each count lands in its slot."""
        stored = [_row("m1", ["r1"]), _row("m2", ["r1"]), _row("m3", ["r2"])]
        produced = [_row("n1", ["u"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u"})

        assert carry == set()
        report = _the_drop_report(caplog)
        message = report.getMessage()
        assert message.startswith("3 stored row(s)"), message
        assert "name 2 record(s) between them" in message, message
        assert "the 1 input(s) this run recorded" in message, message

    def test_the_input_count_is_the_recorded_inputs_not_every_producer_answered(self, caplog):
        """Counted from the recording, not from what the rows answered: here they differ."""
        stored = [_row("m1", ["r1"])]
        produced = [_row("n1", ["u"]), _row("n2", ["w"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u"})

        assert carry == set()
        message = _the_drop_report(caplog).getMessage()
        assert "the 1 input(s) this run recorded" in message, message

    def test_it_is_reported_at_info_not_warning(self, caplog):
        """A minting action below an expansion takes this path on every healthy re-run,
        so a WARNING would fire on each one."""
        stored = [_row("m1", ["r1"])]
        produced = [_row("m2", ["r2"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"r2"})

        assert carry == set()
        report = _the_drop_report(caplog)
        assert report.levelname == "INFO", (
            f"the drop is reported at {report.levelname}; raising it is a decision, since "
            "it fires on every healthy re-run of a minting action below an expansion"
        )


class TestTheCountIsTheRowsActuallyDropped:
    @pytest.mark.parametrize("size", [1, 3, 5])
    def test_the_count_matches_the_rows_not_carried(self, caplog, size):
        stored = [_row(f"m{index}", [f"r{index}"]) for index in range(size)]
        produced = [_row("n1", ["u"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u"})

        dropped = {row["source_guid"] for row in stored} - carry
        assert len(dropped) == size
        report = _the_drop_report(caplog)
        assert report.getMessage().startswith(f"{size} stored row(s)"), report.getMessage()

    def test_neighbouring_rows_that_are_carried_are_not_counted(self, caplog):
        """A merge row and a self-identified row survive the replacement; one row does not."""
        stored = [_row("x1", ["r"]), _row("m1", ["p", "q"]), _row("z1")]
        produced = [_row("y1", ["u"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u"})

        assert carry == {"m1", "z1"}
        message = _the_drop_report(caplog).getMessage()
        assert message.startswith("1 stored row(s)"), message
        assert "name 1 record(s) between them" in message, message

    def test_a_row_answered_again_beside_a_dropped_one_is_not_counted(self, caplog):
        """Not carried is not the same as dropped: z is answered again, so it is replaced."""
        stored = [_row("m1", ["r1"]), _row("z")]
        produced = [_row("n1", ["z"]), _row("n2", ["z"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"z"})

        assert carry == set()
        message = _the_drop_report(caplog).getMessage()
        assert message.startswith("1 stored row(s)"), message

    def test_two_dropped_rows_sharing_an_identity_count_once(self, caplog):
        """Counted by identity, matching what carry-forward would otherwise have kept:
        one row per identity."""
        stored = [_row("g", ["r1"]), _row("g", ["r2"])]
        produced = [_row("n1", ["u"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u"})

        assert carry == set()
        message = _the_drop_report(caplog).getMessage()
        assert message.startswith("1 stored row(s)"), message

    def test_an_identity_another_of_its_rows_still_carries_is_not_counted(self, caplog):
        """The identity is still carried because of its other row, so nothing was lost."""
        stored = [_row("g", ["r1"]), _row("g")]
        produced = [_row("y1", ["u"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u"})

        assert carry == {"g"}
        assert _drop_reports(caplog) == []


class TestNothingDroppedNothingReported:
    """Each case leaves the inference off, or on with nothing for it to drop, and the gate
    logs nothing at any level."""

    def test_a_rerun_over_the_same_inputs(self, caplog):
        stored = [_row("m1", ["r1"]), _row("m2", ["r2"])]
        produced = [_row("m3", ["r1"]), _row("m4", ["r2"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"r1", "r2"})

        assert carry == set()
        assert _gate_records(caplog) == []

    def test_a_run_that_failed(self, caplog):
        stored = [_row("m1", ["r1"]), _row("m2", ["r2"])]
        produced = [_row("r3", state="failed")]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"r3"})

        assert carry == {"m1", "m2"}
        assert _gate_records(caplog) == []

    def test_a_run_that_answered_part_of_its_input(self, caplog):
        stored = [_row("m1", ["r1"]), _row("m2", ["r2"])]
        produced = [_row("m3", ["r3"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"r3", "r4"})

        assert carry == {"m1", "m2"}
        assert _gate_records(caplog) == []

    def test_no_recorded_input(self, caplog):
        stored = [_row("m1", ["r1"]), _row("m2", ["r2"])]
        produced = [_row("m3", ["r3"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced)

        assert carry == {"m1", "m2"}
        assert _gate_records(caplog) == []

    def test_one_stored_producer_still_an_input(self, caplog):
        stored = [_row("m1", ["r1"]), _row("m2", ["r2"])]
        produced = [_row("m3", ["r3"]), _row("m4", ["r2"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"r2", "r3"})

        assert carry == {"m1"}
        assert _gate_records(caplog) == []

    def test_a_replaced_generation_whose_rows_were_all_answered_again(self, caplog):
        """The inference is on, yet each stored row's producer was answered this run."""
        stored = [_row("m1", ["r1"])]
        produced = [_row("m2", ["r1"]), _row("m3", ["u"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u"})

        assert carry == set()
        assert _gate_records(caplog) == []

    def test_a_replaced_generation_whose_row_was_rewritten_under_its_identity(self, caplog):
        stored = [_row("m1", ["r1"])]
        produced = [_row("m1", ["u"])]

        with caplog.at_level(logging.DEBUG, logger=GATE_LOGGER):
            carry = stored_rows_not_reproduced(stored, produced, batch_inputs={"u"})

        assert carry == set()
        assert _gate_records(caplog) == []
