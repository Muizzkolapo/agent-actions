"""A record an action above failed is quarantined online, never judged by the guard (1347).

Batch preparation returns UPSTREAM_UNPROCESSED for such a record before it evaluates the
guard. Online's guard ran first: false for the record, since the failed action's fields
are null, it skipped it as a live `guard_skipped` record or filtered it away, and the
quarantine below never saw it. Both granularities, and FILE mode's pre-scope list paired
by position with what the strategy is handed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import get_guard_evaluator
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.processing.unified import UnifiedProcessor

GUARD = "summarize.summary != null"


class Recording:
    """Answers what it is handed, and keeps what it was handed and paired with it."""

    def __init__(self) -> None:
        self.handed: list[str] = []
        self.paired: list[str] = []

    def invoke(self, records: list[dict[str, Any]], context: ProcessingContext):
        self.handed = [record["source_guid"] for record in records]
        self.paired = [original["source_guid"] for original in context.source_data or []]
        return [
            ProcessingResult.success(
                data=[{**record, "content": {**record["content"], "publish": {"summary": "s"}}}],
                source_guid=record["source_guid"],
            )
            for record in records
        ]


def _record(guid: str, summary: str | None, state: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_guid": guid,
        "content": {
            "source": {"page_content": f"page {guid}"},
            "summarize": None if summary is None else {"summary": summary},
        },
    }
    if state is not None:
        record["_state"] = state
    return record


def _context(behavior: str) -> ProcessingContext:
    return ProcessingContext(
        agent_config={
            "agent_type": "publish",
            "name": "publish",
            "guard": {"clause": GUARD, "behavior": behavior},
        },
        agent_name="publish",
    )


def _by_guid(output: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["source_guid"]: row for row in output}


def _quarantined(row: dict[str, Any]) -> bool:
    return row["_state"] == "cascade_skipped" and row["metadata"]["reason"] == (
        "upstream_unprocessed"
    )


@pytest.mark.parametrize("state", ["failed", "exhausted", "cascade_skipped"])
@pytest.mark.parametrize("behavior", ["skip", "filter"])
def test_a_record_mode_guard_leaves_it_to_the_quarantine(behavior, state):
    strategy = Recording()

    output, stats = UnifiedProcessor().process(
        [_record("blocked", None, state), _record("live", "a summary")],
        _context(behavior),
        strategy,
    )

    rows = _by_guid(output)
    assert _quarantined(rows["blocked"]), rows["blocked"]
    assert rows["live"]["_state"] == "processed"
    assert strategy.handed == ["live"]
    assert (stats.unprocessed, stats.skipped, stats.filtered) == (1, 0, 0)


@pytest.mark.parametrize("behavior", ["skip", "filter"])
def test_a_file_mode_guard_leaves_it_to_the_quarantine(behavior):
    """The strategy is handed the live records, each paired with its own pre-scope record,
    with a quarantined record before them and one the guard turns away between them."""
    records = [
        _record("blocked", None, "failed"),
        _record("first", "a summary"),
        _record("turned_away", None),
        _record("second", "another summary"),
    ]
    raw_records = [{**record, "raw": True} for record in records]
    strategy = Recording()

    output, stats = UnifiedProcessor().process(
        records, _context(behavior), strategy, raw_records=raw_records
    )

    rows = _by_guid(output)
    assert _quarantined(rows["blocked"]), rows["blocked"]
    assert strategy.handed == ["first", "second"]
    assert strategy.paired == ["first", "second"]
    assert stats.unprocessed == (2 if behavior == "skip" else 1)
    assert ("turned_away" in rows) == (behavior == "skip")


def test_the_guard_reads_nothing_of_it():
    """Nothing is loaded for it: the guard is not evaluated on it at all."""
    evaluator = get_guard_evaluator()
    judge = evaluator.evaluate
    judged: list[Any] = []

    def evaluate(**kwargs: Any):
        judged.append(kwargs["item"])
        return judge(**kwargs)

    with patch.object(evaluator, "evaluate", side_effect=evaluate):
        UnifiedProcessor().process(
            [_record("blocked", None, "failed"), _record("live", "a summary")],
            _context("skip"),
            Recording(),
        )

    assert judged == [_record("live", "a summary")["content"]]
