"""A `BETWEEN` range is two numbers or two strings, however it is written (1365).

A range with a NULL or boolean end, ends of two types, or a parenthesised clause for a
range parsed and was false for every record, as the one-value range was.
"""

import pytest

from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser


def _parse(clause: str):
    return WhereClauseParser().parse(clause)


@pytest.mark.parametrize(
    "clause",
    [
        "s.score BETWEEN NULL AND 100",
        "s.score BETWEEN 50 AND NULL",
        "s.score BETWEEN TRUE AND FALSE",
        's.score BETWEEN "a" AND 5',
        "s.score NOT BETWEEN 50 AND NULL",
        "s.score BETWEEN [50, NULL]",
        "s.score BETWEEN [TRUE, FALSE]",
        's.score BETWEEN ["a", 5]',
        "s.score NOT BETWEEN [NULL, 100]",
        "s.score BETWEEN (50 AND 100)",
        "s.score NOT BETWEEN (50 AND 100)",
        "s.score BETWEEN (s.y == 1)",
    ],
)
def test_a_range_whose_ends_cannot_bound_a_value_is_refused(clause):
    result = _parse(clause)

    assert not result.success, f"{clause!r} parsed as {result.ast}"
    assert "BETWEEN [a, b]" in result.error.message


@pytest.mark.parametrize(
    "clause, score, expected",
    [
        ("s.score BETWEEN 1 AND 2.5", 2, True),
        ("s.score BETWEEN 1 AND 2.5", 3, False),
        ("s.score BETWEEN [1, 2.5]", 2.5, True),
        ("s.score BETWEEN s.range", 70, True),
        ("s.score BETWEEN s.range", 10, False),
        ("s.score NOT BETWEEN s.range", 10, True),
        ("s.score NOT BETWEEN s.range", 70, False),
        ("s.y == 1 AND s.score BETWEEN s.range", 70, True),
        ("s.y == 1 OR s.score BETWEEN 50 AND 100", 10, True),
        ("s.y == 2 OR s.score BETWEEN 50 AND 100", 10, False),
        ("s.y == 2 OR s.score BETWEEN 50 AND 100", 70, True),
    ],
)
def test_a_range_of_numbers_or_one_held_in_a_field_is_tested(clause, score, expected):
    result = _parse(clause)

    assert result.success, result.error
    assert result.ast.evaluate({"s": {"score": score, "range": [50, 100], "y": 1}}) is expected
