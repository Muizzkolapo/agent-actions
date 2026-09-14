"""An action whose block declares no rules reports that, not an empty table."""

import io

import pytest
from rich.console import Console

from agent_actions.cli.expect import ExpectReportCommand
from agent_actions.expectations.report import ActionTally, RuleTally


@pytest.fixture
def render():
    def _render(tallies, asked_for=("summarize",)):
        command = ExpectReportCommand(agent="w", action=None, as_json=False)
        command.console = Console(file=io.StringIO(), width=200, no_color=True)
        command._render(list(tallies), list(asked_for))
        return command.console.file.getvalue()

    return _render


def _tally(rules=(), records=3, passed=3):
    return ActionTally(action="summarize", records=records, records_passed=passed, rules=rules)


def test_an_action_with_no_rules_says_so_instead_of_drawing_an_empty_table(render):
    out = render([_tally()])
    assert "no rules" in out
    assert "Pass rate" not in out, "an empty table was drawn for an action with no rules"


def test_an_action_with_rules_still_gets_its_table(render):
    out = render(
        [
            _tally(
                rules=(RuleTally(id="len", type="not_null", severity="error", passed=2, failed=1),)
            )
        ]
    )
    assert "Pass rate" in out
    assert "len" in out


def test_a_rule_id_that_reads_as_markup_is_still_shown(render):
    out = render(
        [_tally(rules=(RuleTally(id="[red]len[/red]", type="not_null", severity="error"),))]
    )
    assert "[red]len[/red]" in out
