"""The rendered listing shows a rule's params verbatim.

Values reach the table from user YAML, where square brackets are ordinary —
a forbidden-phrase list or a regex character class both carry them.
"""

import io

import pytest
from rich.console import Console

from agent_actions.cli.expect import ExpectListCommand


@pytest.fixture
def render():
    def _render(listing):
        command = ExpectListCommand(agent="w", action=None, as_json=False)
        command.console = Console(file=io.StringIO(), width=200, no_color=True)
        command._render(listing)
        return command.console.file.getvalue()

    return _render


def _entry(**rule):
    return [
        {
            "action": "summarize",
            "suite": "summarize:inline",
            "repair": "none",
            "rules": [
                {
                    "id": "r",
                    "type": "matches_regex",
                    "field": "summary",
                    "severity": "error",
                    "params": {},
                    **rule,
                }
            ],
        }
    ]


def test_a_param_that_reads_as_markup_is_still_shown(render):
    out = render(_entry(params={"forbidden": ["[/b]", "[bold]"]}))
    assert "[/b]" in out
    assert "[bold]" in out


def test_a_regex_character_class_survives_rendering(render):
    out = render(_entry(params={"pattern": "^[0-9]+[a-z]{2}$"}))
    assert "^[0-9]+[a-z]{2}$" in out


def test_a_field_name_that_reads_as_markup_is_still_shown(render):
    out = render(_entry(field="[i]odd[/i]"))
    assert "[i]odd[/i]" in out


def test_a_rule_id_that_reads_as_markup_is_still_shown(render):
    out = render(_entry(id="[red]rule[/red]"))
    assert "[red]rule[/red]" in out


def test_the_severity_column_still_reads_as_a_word(render):
    assert "error" in render(_entry())


def test_a_long_rule_id_survives_a_narrow_terminal():
    """The id is the key for matching a listing against a stored verdict, so
    ellipsizing it at an ordinary width makes the listing unusable."""
    import io

    from rich.console import Console

    command = ExpectListCommand(agent="w", action=None, as_json=False)
    command.console = Console(file=io.StringIO(), width=80, no_color=True)
    command._render(
        _entry(
            id="question_stem_is_not_a_verbatim_copy_of_the_source",
            type="no_forbidden_phrases",
            field="question_stem",
        )
    )
    out = command.console.file.getvalue()
    # Rebuild the Rule column: a folded id is spread down it, one piece per row.
    rule_column = "".join(
        line.split("\u2502")[1].strip() for line in out.splitlines() if line.startswith("\u2502")
    )
    assert "question_stem_is_not_a_verbatim_copy_of_the_source" in rule_column, out
    assert "\u2026" not in out, "content was ellipsized away at 80 columns"
