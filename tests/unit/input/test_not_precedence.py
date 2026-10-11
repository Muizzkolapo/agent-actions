"""An unparenthesized `NOT x == 1` negates the comparison, not the field (1382).

`NOT` was the tightest-binding level in the grammar, above every comparison operator,
so `NOT x == 1` read as `(NOT x) == 1`: the comparison was decided by `x`'s truthiness,
never by its value, and the clause was false for every record whose field was truthy.
`NOT` must bind looser than a comparison (including the IS NULL / BETWEEN postfixes)
and tighter than AND/OR, matching `NOT (x == 1)` without requiring the parentheses.
"""

import pytest

from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser


def _holds(clause: str, **data) -> bool:
    result = WhereClauseParser().parse(clause)
    assert result.success, result.error
    return result.ast.evaluate(data)


@pytest.mark.parametrize(
    "clause",
    [
        "NOT s.x == 1",
        "NOT (s.x == 1)",
    ],
)
def test_not_eq_negates_the_comparison_not_the_field(clause):
    assert _holds(clause, s={"x": 5}) is True
    assert _holds(clause, s={"x": 1}) is False


@pytest.mark.parametrize(
    "clause, expected",
    [
        # x = -5: under the bug, `(NOT x) OP 1` collapses to `False OP 1` for any
        # nonzero x (NOT of a truthy number is always False), so a negative x is
        # the value that tells `NOT (x OP 1)` apart from the buggy reading.
        ("NOT s.x < 1", False),  # -5 < 1 is True, NOT -> False
        ("NOT s.x <= 1", False),  # -5 <= 1 is True, NOT -> False
        ("NOT s.x > 1", True),  # -5 > 1 is False, NOT -> True
        ("NOT s.x >= 1", True),  # -5 >= 1 is False, NOT -> True
        ("NOT s.x != 1", False),  # -5 != 1 is True, NOT -> False
    ],
)
def test_not_binds_looser_than_every_comparison_operator(clause, expected):
    assert _holds(clause, s={"x": -5}) is expected


def test_not_in_negates_the_membership_test():
    assert _holds("NOT s.x IN [1, 2]", s={"x": 5}) is True
    assert _holds("NOT s.x IN [1, 2]", s={"x": 1}) is False


def test_not_like_negates_the_pattern_match():
    assert _holds('NOT s.name LIKE "rock%"', s={"name": "jazz"}) is True
    assert _holds('NOT s.name LIKE "rock%"', s={"name": "rock and roll"}) is False


def test_not_between_negates_the_range_test():
    assert _holds("NOT s.x BETWEEN 1 AND 10", s={"x": 50}) is True
    assert _holds("NOT s.x BETWEEN 1 AND 10", s={"x": 5}) is False


def test_not_is_null_negates_the_null_check():
    assert _holds("NOT s.x IS NULL", s={"x": 5}) is True
    assert _holds("NOT s.x IS NULL", s={"x": None}) is False


@pytest.mark.parametrize(
    "clause",
    [
        "NOT s.x == 1 AND s.y == 2",
        "(NOT s.x == 1) AND s.y == 2",
    ],
)
def test_not_binds_tighter_than_and(clause):
    # `NOT (x==1 AND y==2)` would be True for x=1,y=5; the correct reading
    # `(NOT x==1) AND y==2` is False for x=1,y=5 and True for x=5,y=2.
    assert _holds(clause, s={"x": 1, "y": 5}) is False
    assert _holds(clause, s={"x": 5, "y": 2}) is True


@pytest.mark.parametrize(
    "clause",
    [
        "NOT s.x == 1 OR s.y == 2",
        "(NOT s.x == 1) OR s.y == 2",
    ],
)
def test_not_binds_tighter_than_or(clause):
    assert _holds(clause, s={"x": 1, "y": 5}) is False
    assert _holds(clause, s={"x": 1, "y": 2}) is True
    assert _holds(clause, s={"x": 5, "y": 5}) is True


def test_bare_not_field_still_negates_the_fields_truthiness():
    assert _holds("NOT s.flag", s={"flag": False}) is True
    assert _holds("NOT s.flag", s={"flag": True}) is False
