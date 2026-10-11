"""One of `IS NULL`, `IS NOT NULL` or a `BETWEEN a AND b` range follows an operand (1365).

Two in a row compare a boolean, so the clause is the same for every record.
"""

import pytest

from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser


@pytest.mark.parametrize(
    "clause",
    [
        "s.x IS NULL BETWEEN 0 AND 1",
        "s.x IS NOT NULL NOT BETWEEN 0 AND 1",
        "s.x BETWEEN 1 AND 10 IS NULL",
        "s.x BETWEEN 1 AND 10 IS NOT NULL",
        "s.x BETWEEN 1 AND 10 BETWEEN 0 AND 1",
        "s.x IS NULL IS NULL",
        "s.x IS NOT NULL IS NOT NULL",
        "s.x IS NULL IS NOT NULL AND s.y == 1",
    ],
)
def test_a_second_postfix_on_one_operand_is_refused(clause):
    result = WhereClauseParser().parse(clause)

    assert not result.success, f"{clause!r} parsed as {result.ast}"
    assert "parentheses" in result.error.message


@pytest.mark.parametrize("x, is_null", [(None, True), (0, False), (7, False)])
def test_is_null_alone_still_takes_no_right_operand(x, is_null):
    parser = WhereClauseParser()

    assert parser.parse("s.x IS NULL").ast.evaluate({"s": {"x": x}}) is is_null
    assert parser.parse("s.x IS NOT NULL").ast.evaluate({"s": {"x": x}}) is not is_null
    assert parser.parse("s.x IS NULL").ast.root.right is None


@pytest.mark.parametrize(
    "clause, x, expected",
    [
        ("s.x IS NULL OR s.x BETWEEN 1 AND 10", None, True),
        ("s.x IS NULL OR s.x BETWEEN 1 AND 10", 5, True),
        ("s.x IS NULL OR s.x BETWEEN 1 AND 10", 11, False),
        ("s.x IS NOT NULL AND s.x NOT BETWEEN 1 AND 10", 11, True),
        ("s.x IS NOT NULL AND s.x NOT BETWEEN 1 AND 10", 5, False),
        ("s.x IS NOT NULL == TRUE", 5, True),
        ("s.x IS NOT NULL == TRUE", None, False),
    ],
)
def test_a_postfix_on_each_operand_is_read_as_before(clause, x, expected):
    result = WhereClauseParser().parse(clause)

    assert result.success, result.error
    assert result.ast.evaluate({"s": {"x": x}}) is expected
