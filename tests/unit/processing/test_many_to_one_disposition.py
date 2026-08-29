"""A documented many-to-one collapse must not read as dropped records.

``FileUDFResult(outputs=[{"source_index": [0, 1, 2, ...], ...}])`` is the
framework's own recommended shape for a tool that folds N inputs into fewer
outputs.  The missing-record safety net builds its "accounted for" set from
``structured_data``'s reattached ``source_guid``, and a collapsed output only
carries the *first* contributing input's guid — so the other N-1 inputs look
dropped and are tombstoned ``tool_missing_record``.  The data written is right;
the audit trail that ``agac dispositions`` reports is wrong.
"""

from __future__ import annotations

from unittest.mock import patch

from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.record.reasons import TOOL_MISSING_RECORD
from agent_actions.record.tracking import TrackedItem
from agent_actions.utils.udf_management.registry import FileUDFResult


def _context(agent_name: str = "collect_questions") -> ProcessingContext:
    return ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name=agent_name,
    )


def _records(*guids: str) -> list[dict]:
    return [{"source_guid": g, "content": {"prev": {"id": i}}} for i, g in enumerate(guids)]


def _invoke(records: list[dict], raw_response) -> list:
    context = _context()
    context.source_data = records
    with patch(
        "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
        return_value=(raw_response, True),
    ):
        return FileToolStrategy().invoke(records, context)


def _tombstoned(results: list) -> list[str]:
    return sorted(
        r.source_guid
        for r in results
        if r.status == ProcessingStatus.UNPROCESSED and r.skip_reason == TOOL_MISSING_RECORD
    )


class TestACollapseAccountsForEveryContributor:
    def test_ten_into_one_tombstones_nobody(self):
        """The live shape: collect_questions folds 10 authored records into one file."""
        guids = [f"r{i}" for i in range(10)]
        records = _records(*guids)

        results = _invoke(
            records,
            FileUDFResult(outputs=[{"source_index": list(range(10)), "data": {"written": 10}}]),
        )

        assert _tombstoned(results) == []

    def test_the_collapse_still_produces_its_output(self):
        records = _records("r1", "r2", "r3")

        results = _invoke(
            records,
            FileUDFResult(outputs=[{"source_index": [0, 1, 2], "data": {"written": 3}}]),
        )

        successes = [r for r in results if r.status == ProcessingStatus.SUCCESS]
        assert len(successes) == 1
        assert successes[0].data[0]["written"] == 3

    def test_two_groups_collapse_independently(self):
        records = _records("r1", "r2", "r3", "r4")

        results = _invoke(
            records,
            FileUDFResult(
                outputs=[
                    {"source_index": [0, 1], "data": {"group": "a"}},
                    {"source_index": [2, 3], "data": {"group": "b"}},
                ]
            ),
        )

        assert _tombstoned(results) == []

    def test_a_contributor_left_out_of_every_group_is_still_tombstoned(self):
        """The safety net must keep catching genuinely dropped records."""
        records = _records("r1", "r2", "r3")

        results = _invoke(
            records,
            FileUDFResult(outputs=[{"source_index": [0, 1], "data": {"group": "a"}}]),
        )

        assert _tombstoned(results) == ["r3"]


class TestTheOneToOneCasesAreUnchanged:
    def test_a_dropped_record_is_still_tombstoned(self):
        records = _records("r1", "r2", "r3")

        results = _invoke(
            records,
            [TrackedItem({"v": 1}, source_index=0), TrackedItem({"v": 3}, source_index=2)],
        )

        assert _tombstoned(results) == ["r2"]

    def test_a_full_passthrough_tombstones_nobody(self):
        records = _records("r1", "r2")

        results = _invoke(
            records,
            [TrackedItem({"v": 1}, source_index=0), TrackedItem({"v": 2}, source_index=1)],
        )

        assert _tombstoned(results) == []
