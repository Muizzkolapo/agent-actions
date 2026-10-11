"""A guard that compares a field to a string containing and/or/not/in/etc. parses (1383).

`WhereClauseParser._validate_field_names` ran a naive regex split over the raw clause
text before the real grammar, splitting on operator characters and the words `and`,
`or`, `not`, `in`, `like`, `between`, `is`, `null` and `contains` — with no regard for
quotes or parentheses. A string literal containing one of those words, a parenthesized
clause ending in a field, and every function call were refused with a misleading
"Invalid field names detected", though the real grammar (which restricts a field name to
`[a-zA-Z_][a-zA-Z0-9_]*` segments) would have accepted or correctly refused all of them.
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
        ('s.title == "rock and roll"', {"title": "rock and roll"}, True),
        ('s.title == "rock and roll"', {"title": "jazz"}, False),
        ('s.title != "this or that"', {"title": "jazz"}, True),
        ('s.title == "is not available"', {"title": "is not available"}, True),
        ('s.title != "between us"', {"title": "jazz"}, True),
        ('s.title == "in the end"', {"title": "in the end"}, True),
        ('s.title == "sounds like this"', {"title": "sounds like this"}, True),
        ('s.title == "null and void"', {"title": "null and void"}, True),
        ('s.title == "contains everything"', {"title": "contains everything"}, True),
    ],
)
def test_a_string_literal_holding_a_reserved_word_parses(clause, data, expected):
    assert _holds(clause, s=data) is expected


def test_a_parenthesized_clause_ending_in_a_bare_field_parses():
    assert _holds("(s.x == 5 OR s.done)", s={"x": 5, "done": False}) is True
    assert _holds("(s.x == 5 OR s.done)", s={"x": 1, "done": True}) is True
    assert _holds("(s.x == 5 OR s.done)", s={"x": 1, "done": False}) is False


class TestFunctionCalls:
    def test_length_counts_characters_or_items(self):
        assert _holds("LENGTH(s.name) > 3", s={"name": "jazz"}) is True
        assert _holds("LENGTH(s.name) > 3", s={"name": "ok"}) is False
        assert _holds("LENGTH(s.tags) >= 2", s={"tags": ["a", "b"]}) is True

    def test_length_of_null_is_zero(self):
        assert _holds("LENGTH(s.name) == 0", s={"name": None}) is True

    def test_upper_and_lower_normalize_case(self):
        assert _holds('UPPER(s.category) == "SPAM"', s={"category": "spam"}) is True
        assert _holds('LOWER(s.category) == "spam"', s={"category": "SPAM"}) is True

    def test_trim_strips_whitespace(self):
        assert _holds('TRIM(s.title) == "ok"', s={"title": "  ok  "}) is True

    def test_a_field_inside_a_function_call_still_needs_its_prefix_to_resolve(self):
        """A field inside a call resolves exactly as one outside a call does:
        unnamespaced fails the same way, not silently."""
        from agent_actions.input.preprocessing.parsing.ast_nodes import MissingFieldError

        result = WhereClauseParser().parse("LENGTH(name) > 0")
        assert result.success, result.error
        with pytest.raises(MissingFieldError, match="name"):
            result.ast.evaluate({"s": {"name": "x"}})

    def test_an_array_literal_argument_is_refused(self):
        """Not a shape LENGTH/UPPER/LOWER/TRIM take -- each takes exactly one
        field or literal. Pins the refusal so a future change decides this on
        purpose, not as an accidental side effect of a grammar edit."""
        result = WhereClauseParser().parse("LENGTH([1, 2, 3]) > 0")
        assert not result.success

    def test_a_nested_function_call_argument_is_refused(self):
        """Not supported -- same reasoning as the array-literal refusal above."""
        result = WhereClauseParser().parse("LENGTH(TRIM(s.name)) > 0")
        assert not result.success
