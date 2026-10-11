"""`x BETWEEN a AND b` tests the range, as `x BETWEEN [a, b]` does (1365).

The clause parsed as `(x BETWEEN a) AND b`. `BETWEEN` with one number for its range is
false for every value, so the clause was false for every record, and true for every
record under `NOT (...)`.
"""

import pytest

from agent_actions.input.preprocessing.parsing.ast_nodes import (
    ComparisonNode,
    ComparisonOperator,
    LiteralNode,
)
from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

BELOW, LOW, INSIDE, HIGH, ABOVE = 49, 50, 70, 100, 101


def _holds(clause: str, **data) -> bool:
    result = WhereClauseParser().parse(clause)
    assert result.success, result.error
    return result.ast.evaluate(data)


def _refusal(clause: str) -> str:
    result = WhereClauseParser().parse(clause)
    assert not result.success, f"{clause!r} parsed as {result.ast}"
    return result.error.message


@pytest.mark.parametrize(
    "clause",
    [
        "s.score BETWEEN 50 AND 100",
        "s.score BETWEEN [50, 100]",
        "s.score between 50 and 100",
        "(s.score BETWEEN 50 AND 100)",
        "NOT (s.score NOT BETWEEN 50 AND 100)",
    ],
)
@pytest.mark.parametrize(
    "score, inside",
    [(BELOW, False), (LOW, True), (INSIDE, True), (HIGH, True), (ABOVE, False)],
)
def test_between_holds_inside_the_range_and_at_its_bounds(clause, score, inside):
    assert _holds(clause, s={"score": score}) is inside


@pytest.mark.parametrize(
    "clause",
    [
        "s.score NOT BETWEEN 50 AND 100",
        "s.score NOT BETWEEN [50, 100]",
        "NOT (s.score BETWEEN 50 AND 100)",
        "NOT (s.score BETWEEN [50, 100])",
    ],
)
@pytest.mark.parametrize(
    "score, outside",
    [(BELOW, True), (LOW, False), (INSIDE, False), (HIGH, False), (ABOVE, True)],
)
def test_not_between_holds_outside_the_range_only(clause, score, outside):
    assert _holds(clause, s={"score": score}) is outside


def test_the_two_forms_parse_to_the_same_comparison():
    parser = WhereClauseParser()
    written = parser.parse("s.score BETWEEN 50 AND 100").ast.root
    listed = parser.parse("s.score BETWEEN [50, 100]").ast.root

    assert isinstance(written, ComparisonNode)
    assert written.operator is ComparisonOperator.BETWEEN
    assert written.right == LiteralNode([50, 100])
    assert written == listed


@pytest.mark.parametrize(
    "clause, score, y, expected",
    [
        ("s.score BETWEEN 1 AND 10 AND s.y == 1", 5, 1, True),
        ("s.score BETWEEN 1 AND 10 AND s.y == 1", 5, 2, False),
        ("s.score BETWEEN 1 AND 10 AND s.y == 1", 11, 1, False),
        ("s.y == 1 AND s.score BETWEEN 1 AND 10", 5, 1, True),
        ("s.y == 1 AND s.score BETWEEN 1 AND 10", 11, 1, False),
        ("s.score BETWEEN 1 AND 10 OR s.y == 1", 11, 1, True),
        ("s.score BETWEEN 1 AND 10 OR s.y == 1", 11, 2, False),
        ("s.score BETWEEN 1 AND 10 OR s.y == 1", 5, 2, True),
        ("s.score NOT BETWEEN 1 AND 10 AND s.y == 1", 11, 1, True),
        ("s.score NOT BETWEEN 1 AND 10 AND s.y == 1", 5, 1, False),
        ("s.score BETWEEN 1 AND 10 AND s.y BETWEEN 1 AND 2", 5, 2, True),
        ("s.score BETWEEN 1 AND 10 AND s.y BETWEEN 1 AND 2", 5, 3, False),
        ("s.score BETWEEN [1, 10] AND s.y == 1", 5, 1, True),
        ("s.score BETWEEN [1, 10] AND s.y == 1", 5, 2, False),
    ],
)
def test_a_range_combines_with_and_and_or(clause, score, y, expected):
    assert _holds(clause, s={"score": score, "y": y}) is expected


@pytest.mark.parametrize(
    "name, inside",
    [("alpha", False), ("bravo", True), ("charlie", True), ("delta", True), ("echo", False)],
)
def test_a_range_of_strings(name, inside):
    assert _holds('s.name BETWEEN "bravo" AND "delta"', s={"name": name}) is inside


def test_a_range_of_negative_and_decimal_bounds():
    assert _holds("s.score BETWEEN -1.5 AND 0.5", s={"score": 0}) is True
    assert _holds("s.score BETWEEN -1.5 AND 0.5", s={"score": 1}) is False


@pytest.mark.parametrize(
    "clause",
    [
        "s.score BETWEEN 50",
        "s.score NOT BETWEEN 50",
        "NOT (s.score BETWEEN 50)",
        "s.score BETWEEN [50]",
        "s.score BETWEEN [1, 2, 3]",
        's.score BETWEEN "50"',
        "s.score BETWEEN 50 OR s.y == 1",
    ],
)
def test_a_range_that_is_not_two_values_is_refused(clause):
    """It was false for every record: `BETWEEN` needs both ends of its range."""
    assert "BETWEEN [a, b]" in _refusal(clause)


@pytest.mark.parametrize(
    "clause",
    [
        "s.score BETWEEN s.low AND s.high",
        "s.score BETWEEN s.low AND 100",
        "s.score BETWEEN 50 AND s.high",
        "s.score NOT BETWEEN s.low AND s.high",
        "s.score BETWEEN s.low AND s.high AND s.y == 1",
    ],
)
def test_a_bound_that_is_not_a_literal_is_refused(clause):
    """It read as `(x BETWEEN low) AND high`, which never tests the range."""
    assert "BETWEEN [a, b]" in _refusal(clause)
