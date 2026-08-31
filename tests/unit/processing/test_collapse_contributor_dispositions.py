"""Every contributor to a many-to-one collapse gets a disposition row.

A collapsed output carries only its first parent's guid, so the other N-1
consumed inputs would leave no row at the consuming action; they get
``success`` + ``reason=collapsed_into_output`` under the one-row-per-input
contract, distinguishing "produced a record" from "was folded into one".
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.record.tracking import TrackedItem
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.udf_management.registry import FileUDFResult

ACTION = "collect_questions"
AGENT_CONFIG = {"kind": "tool", "granularity": "file"}


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "test.db"), workflow_name="test_workflow")
    b.initialize()
    return b


def _records(*guids: str) -> list[dict]:
    return [{"source_guid": g, "content": {"prev": {"id": i}}} for i, g in enumerate(guids)]


def _run_pipeline(records: list[dict], raw_response, backend) -> None:
    context = ProcessingContext(agent_config=AGENT_CONFIG, agent_name=ACTION)
    context.source_data = records
    with patch(
        "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
        return_value=(raw_response, True),
    ):
        results = FileToolStrategy().invoke(records, context)
    ResultCollector.collect_results(
        results,
        AGENT_CONFIG,
        ACTION,
        is_first_stage=False,
        storage_backend=backend,
    )


def _rows(backend) -> dict[str, dict]:
    return {r["record_id"]: r for r in backend.get_disposition(ACTION)}


class TestEveryContributorHasARow:
    def test_ten_into_one_accounts_for_all_ten(self, backend):
        """The live shape: 10 authored records fold into one written file."""
        guids = [f"r{i}" for i in range(10)]
        _run_pipeline(
            _records(*guids),
            FileUDFResult(outputs=[{"source_index": list(range(10)), "data": {"written": 10}}]),
            backend,
        )

        rows = _rows(backend)
        assert sorted(rows) == sorted(guids), "one disposition row per consumed input"
        assert all(r["disposition"] == "success" for r in rows.values())

    def test_contributors_are_distinguishable_from_the_carrier(self, backend):
        _run_pipeline(
            _records("r1", "r2", "r3"),
            FileUDFResult(outputs=[{"source_index": [0, 1, 2], "data": {"written": 3}}]),
            backend,
        )

        rows = _rows(backend)
        # The carrier produced the output record — its row carries no reason.
        assert rows["r1"]["disposition"] == "success"
        assert rows["r1"]["reason"] is None
        # The folded contributors say so.
        for guid in ("r2", "r3"):
            assert rows[guid]["disposition"] == "success"
            assert rows[guid]["reason"] == "collapsed_into_output"

    def test_two_groups_account_their_own_contributors(self, backend):
        _run_pipeline(
            _records("r1", "r2", "r3", "r4"),
            FileUDFResult(
                outputs=[
                    {"source_index": [0, 1], "data": {"group": "a"}},
                    {"source_index": [2, 3], "data": {"group": "b"}},
                ]
            ),
            backend,
        )

        rows = _rows(backend)
        assert sorted(rows) == ["r1", "r2", "r3", "r4"]
        collapsed = sorted(g for g, r in rows.items() if r["reason"] == "collapsed_into_output")
        assert collapsed == ["r2", "r4"]

    def test_the_carrier_gets_exactly_one_row(self, backend):
        """The carrier must not also be written as a contributor row."""
        _run_pipeline(
            _records("r1", "r2"),
            FileUDFResult(outputs=[{"source_index": [0, 1], "data": {"written": 2}}]),
            backend,
        )

        carrier_rows = [r for r in backend.get_disposition(ACTION) if r["record_id"] == "r1"]
        assert len(carrier_rows) == 1
        assert carrier_rows[0]["reason"] is None


class TestTheSafetyNetsStillHold:
    def test_a_genuinely_dropped_record_is_not_marked_collapsed(self, backend):
        """A record no output accounts for stays unprocessed — collapse rows
        must never absorb the missing-record tombstone path."""
        _run_pipeline(
            _records("r1", "r2", "r3"),
            FileUDFResult(outputs=[{"source_index": [0, 1], "data": {"group": "a"}}]),
            backend,
        )

        all_rows = backend.get_disposition(ACTION)
        # r3 must have exactly its tombstone row — an implementation writing
        # contributor rows for every input would add a phantom success row
        # beside it (the UNIQUE key allows both to coexist).
        r3_rows = [r for r in all_rows if r["record_id"] == "r3"]
        assert len(r3_rows) == 1
        assert r3_rows[0]["disposition"] == "unprocessed"
        assert len(all_rows) == 3

        rows = _rows(backend)
        assert rows["r2"]["reason"] == "collapsed_into_output"

    def test_one_to_one_passthrough_writes_no_collapsed_rows(self, backend):
        _run_pipeline(
            _records("r1", "r2"),
            [TrackedItem({"v": 1}, source_index=0), TrackedItem({"v": 2}, source_index=1)],
            backend,
        )

        rows = _rows(backend)
        assert sorted(rows) == ["r1", "r2"]
        assert all(r["reason"] != "collapsed_into_output" for r in rows.values())

    def test_a_failed_collapse_writes_no_contributor_rows(self, backend):
        """A parse-error collapse is converted to FAILED before collection —
        its contributors must not be recorded as successfully collapsed."""
        _run_pipeline(
            _records("r1", "r2", "r3"),
            FileUDFResult(
                outputs=[{"source_index": [0, 1, 2], "data": {"_parse_error": "bad json"}}]
            ),
            backend,
        )

        all_rows = backend.get_disposition(ACTION)
        assert all(r["reason"] != "collapsed_into_output" for r in all_rows)
        rows = {r["record_id"]: r for r in all_rows}
        assert rows["r1"]["disposition"] == "failed"

    def test_action_classification_is_unchanged(self, backend):
        """Volume consumers must classify the action the same way after the fix."""
        _run_pipeline(
            _records("r1", "r2", "r3"),
            FileUDFResult(outputs=[{"source_index": [0, 1, 2], "data": {"written": 3}}]),
            backend,
        )

        assert backend.has_successful_items(ACTION) is True
        assert backend.get_failed_items(ACTION) == []
