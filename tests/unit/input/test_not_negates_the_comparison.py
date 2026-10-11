"""`NOT x == 1`, unparenthesised, negates the comparison, not the field (1382).

The grammar read `NOT` as the tightest level, so it bound to the field before any
comparison ran: `NOT x == 1` parsed as `(NOT x) == 1`. `NOT x` is a boolean, so the
clause was decided by `x`'s truthiness rather than its value, and was false for
every record whose field was truthy. Only the parenthesised form, `NOT (x == 1)`,
negated the comparison.
"""

import pytest

from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser


def _holds(clause: str, **data) -> bool:
    result = WhereClauseParser().parse(clause)
    assert result.success, result.error
    return result.ast.evaluate(data)


@pytest.mark.parametrize(
    "clause, data, expected",
    [
        ("NOT s.x == 1", {"s": {"x": 1}}, False),
        ("NOT s.x == 1", {"s": {"x": 5}}, True),
        ("not s.x == 1", {"s": {"x": 5}}, True),
        ("NOT s.x != 1", {"s": {"x": 1}}, True),
        ("NOT s.x != 1", {"s": {"x": 5}}, False),
        ("NOT s.x IN [1, 2]", {"s": {"x": 1}}, False),
        ("NOT s.x IN [1, 2]", {"s": {"x": 5}}, True),
        ('NOT s.name LIKE "rock%"', {"s": {"name": "rock and roll"}}, False),
        ('NOT s.name LIKE "rock%"', {"s": {"name": "jazz"}}, True),
        ("NOT s.x BETWEEN 1 AND 10", {"s": {"x": 5}}, False),
        ("NOT s.x BETWEEN 1 AND 10", {"s": {"x": 50}}, True),
        ("NOT s.x IS NULL", {"s": {"x": 1}}, True),
        ("NOT s.x IS NULL", {"s": {"x": None}}, False),
    ],
)
def test_not_negates_the_whole_comparison(clause, data, expected):
    assert _holds(clause, **data) is expected


@pytest.mark.parametrize(
    "clause, data, expected",
    [
        ("NOT (s.x == 1)", {"s": {"x": 1}}, False),
        ("NOT (s.x == 1)", {"s": {"x": 5}}, True),
    ],
)
def test_the_parenthesised_form_keeps_working(clause, data, expected):
    assert _holds(clause, **data) is expected


@pytest.mark.parametrize(
    "x, expected",
    [(1, False), (0, True), ("", True), ("a", False), (None, True)],
)
def test_a_bare_not_on_a_field_negates_its_truthiness(x, expected):
    """The one form that puts NOT directly on an operand, not a comparison."""
    assert _holds("NOT s.x", s={"x": x}) is expected


@pytest.mark.parametrize(
    "clause, x, y, expected",
    [
        ("NOT s.x == 1 AND s.y == 1", 5, 1, True),
        ("NOT s.x == 1 AND s.y == 1", 1, 1, False),
        ("s.y == 1 AND NOT s.x == 1", 5, 1, True),
        ("NOT s.x == 1 OR s.y == 1", 1, 1, True),
        ("NOT s.x == 1 OR s.y == 1", 1, 2, False),
    ],
)
def test_not_combines_with_and_and_or(clause, x, y, expected):
    assert _holds(clause, s={"x": x, "y": y}) is expected
