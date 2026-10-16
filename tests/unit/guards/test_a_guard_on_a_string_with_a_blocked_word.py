"""A blocked word inside a quoted string is a data value, not code (1400)."""

import pytest

from agent_actions.errors import ValidationError
from agent_actions.guards.guard_parser import GuardParser, GuardType
from agent_actions.output.response.config_schema import WhereClauseConfig
from agent_actions.utils.constants import contains_dangerous_pattern


@pytest.mark.parametrize(
    "clause",
    [
        's.status == "open"',
        's.type == "file"',
        "s.status == 'open'",
        's.note == "please eval this"',
        's.note == "say \\"open\\" twice"',
        's.a == "open" and s.b == "file"',
    ],
)
def test_a_guard_comparing_to_a_string_with_a_blocked_word_parses(clause):
    parsed = GuardParser.parse(clause)

    assert parsed.type == GuardType.SQL
    assert parsed.expression == clause


@pytest.mark.parametrize(
    ("clause", "word"),
    [
        ("open(s.path)", "open"),
        ('eval("x")', "eval"),
        ('s.status == "open" and exec(s.x)', "exec"),
        ('s.a == "unterminated open', "open"),
    ],
)
def test_a_blocked_word_outside_a_string_is_still_refused(clause, word):
    with pytest.raises(ValidationError, match=f"dangerous pattern: {word}"):
        GuardParser.parse(clause)


def test_a_where_clause_comparing_to_a_string_with_a_blocked_word_is_accepted():
    assert WhereClauseConfig(clause="status = 'open'").clause == "status = 'open'"


def test_a_where_clause_calling_a_blocked_word_is_still_refused():
    with pytest.raises(ValidationError, match="dangerous operation: open"):
        WhereClauseConfig(clause="open('x')")


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('x == "exec"', None),
        ("x == 'dir'", None),
        ('exec("x")', "exec"),
        ('x == "a\\"" or dir', "dir"),
    ],
)
def test_contains_dangerous_pattern_skips_quoted_literals(expression, expected):
    assert contains_dangerous_pattern(expression) == expected
