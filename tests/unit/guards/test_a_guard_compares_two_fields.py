"""A guard clause may compare a field with another dotted field."""

from __future__ import annotations

import pytest

from agent_actions.guards.consolidated_guard import GuardBehavior
from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.input.preprocessing.filtering.guard_filter import (
    ErrorCategory,
    FilterItemRequest,
    GuardFilter,
)
from agent_actions.validation.preflight.guard_validation import validate_guard_conditions

CLAUSE = "tag.score <= tag.limit"


def _configs(clause: str) -> dict:
    return {"check": {"guard": {"clause": clause, "behavior": "filter"}}}


def test_preflight_accepts_two_dotted_fields():
    assert validate_guard_conditions(_configs(CLAUSE)) == []


def test_preflight_still_refuses_an_undotted_right_side():
    errors = validate_guard_conditions(_configs("tag.score <= limit"))
    assert (
        "Action 'check': guard condition 'tag.score <= limit' compares field 'tag.score' to "
        "bare identifier 'limit'. If 'limit' is a string value, quote it: "
        'tag.score <= "limit"'
    ) in errors


def test_a_record_missing_the_right_field_does_not_poison_the_next():
    guard = GuardFilter()

    first = guard.filter_item(FilterItemRequest(data={"tag": {"score": 3}}, condition=CLAUSE))
    second = guard.filter_item(
        FilterItemRequest(data={"tag": {"score": 3, "limit": 5}}, condition=CLAUSE)
    )

    assert first.error_category != ErrorCategory.SEMANTIC
    assert (second.success, second.matched) == (True, True)


@pytest.mark.parametrize(
    ("record", "runs"),
    [
        ({"tag": {"score": 3, "limit": 5}}, True),
        ({"tag": {"score": 9, "limit": 5}}, False),
        ({"tag": {"score": 3}}, False),
        ({"tag": {"limit": 5}}, False),
    ],
    ids=["holds-both-true", "holds-both-false", "lacks-right", "lacks-left"],
)
def test_a_missing_field_on_either_side_counts_as_not_matched(record, runs):
    result = GuardEvaluator(GuardFilter()).evaluate(
        {"content": record}, {"clause": CLAUSE, "behavior": "filter"}
    )

    assert result.should_execute is runs
    if not runs:
        assert result.behavior == GuardBehavior.FILTER
