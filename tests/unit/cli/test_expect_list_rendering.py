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
