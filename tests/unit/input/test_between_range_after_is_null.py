"""A range written after `IS NULL` is not dropped from the clause (1365)."""

import pytest

from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser


@pytest.mark.parametrize(
    "written, listed",
    [
        ("s.x IS NULL BETWEEN 0 AND 1", "s.x IS NULL BETWEEN [0, 1]"),
        ("s.x IS NOT NULL NOT BETWEEN 0 AND 1", "s.x IS NOT NULL NOT BETWEEN [0, 1]"),
        ("s.x IS NULL BETWEEN 5 AND 9", "s.x IS NULL BETWEEN [5, 9]"),
    ],
)
@pytest.mark.parametrize("x", [None, 0, 7])
def test_a_range_after_is_null_reads_as_the_list_form_does(written, listed, x):
    parser = WhereClauseParser()
    range_form, list_form = parser.parse(written), parser.parse(listed)

    assert range_form.success and list_form.success
    assert range_form.ast.root == list_form.ast.root
    assert range_form.ast.evaluate({"s": {"x": x}}) == list_form.ast.evaluate({"s": {"x": x}})


@pytest.mark.parametrize("x, is_null", [(None, True), (0, False), (7, False)])
def test_is_null_alone_still_takes_no_right_operand(x, is_null):
    parser = WhereClauseParser()

    assert parser.parse("s.x IS NULL").ast.evaluate({"s": {"x": x}}) is is_null
    assert parser.parse("s.x IS NOT NULL").ast.evaluate({"s": {"x": x}}) is not is_null
    assert parser.parse("s.x IS NULL").ast.root.right is None
