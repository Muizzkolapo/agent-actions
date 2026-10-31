"""Pre-flight refuses valid clauses as "Invalid field names detected" (1383).

A raw-text pre-check split the clause on operator words, ignoring quotes and
parens, and rejected anything whose pieces didn't individually look like a
field name — a string literal containing "and", a paren ending in a field, a
function call. The grammar after it already enforces the same shape correctly.
"""

from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser


def _parses(clause: str, **data) -> bool:
    result = WhereClauseParser().parse(clause)
    assert result.success, result.error
    return result.ast.evaluate(data)


def test_a_string_literal_containing_and_parses():
    assert _parses('s.genre == "rock and roll"', s={"genre": "rock and roll"}) is True
    assert _parses('s.genre == "rock and roll"', s={"genre": "jazz"}) is False


def test_a_string_literal_containing_or_parses():
    assert _parses('s.title != "this or that"', s={"title": "something else"}) is True


def test_a_parenthesised_clause_ending_in_a_field_parses():
    assert _parses("(s.x == 5 OR s.done)", s={"x": 5, "done": False}) is True
    assert _parses("(s.x == 5 OR s.done)", s={"x": 1, "done": False}) is False


def test_a_function_call_parses():
    """A field argument (`LENGTH(s.name)`) hits a separate, unrelated parse gap (1397)."""
    assert _parses('LENGTH("hello") > 3') is True
    assert _parses('LENGTH("hi") > 3') is False


def test_each_blocklisted_word_inside_a_string_literal_parses():
    for word in ("and", "or", "not", "in", "is", "like", "between", "null", "contains"):
        clause = f's.text == "a {word} b"'
        result = WhereClauseParser().parse(clause)
        assert result.success, f"{clause!r} should parse, got: {result.error}"
        assert result.ast.evaluate({"s": {"text": f"a {word} b"}}) is True
