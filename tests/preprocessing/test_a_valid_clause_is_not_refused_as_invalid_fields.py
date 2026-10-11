"""Pre-flight refuses valid clauses as "Invalid field names detected" (1383).

Before the grammar runs, `_validate_field_names` splits the raw clause text on
operator characters and on the words and/or/not/in/like/between/is/null/contains,
and checks that every piece starting with a letter is a field name. It splits
inside quoted strings and takes no account of parentheses, so it refuses: a string
literal containing one of those words, a parenthesised clause whose last operand
is a field, and every function call. The grammar that runs after this pre-check
already restricts a field name to the same shape correctly, so the pre-check
rejects nothing the grammar would wrongly accept.
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
