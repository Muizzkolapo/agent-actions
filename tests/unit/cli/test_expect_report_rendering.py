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
    return ActionTally(
        action="summarize",
        records=records,
        records_passed=passed,
        rules=rules,
        records_total=records,
    )


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


def test_records_without_a_verdict_are_flagged_beside_the_rate(render):
    out = render(
        [ActionTally(action="summarize", records=3, records_passed=3, rules=(), records_total=7)]
    )
    assert "4 records carried no verdict" in out


def test_a_fully_verified_action_carries_no_such_warning(render):
    out = render(
        [ActionTally(action="summarize", records=3, records_passed=3, rules=(), records_total=3)]
    )
    assert "carried no verdict" not in out


@pytest.mark.parametrize(
    ("passed", "total", "forbidden"),
    [
        (9996, 10000, "100"),
        (4, 10000, "0%"),
        (999999, 1000000, "100"),
    ],
)
def test_a_rate_that_is_not_perfect_never_renders_as_perfect(render, passed, total, forbidden):
    """A ten-thousand-record action with four failures is not a clean 100%."""
    out = render(
        [
            ActionTally(
                action="a", records=total, records_passed=passed, rules=(), records_total=total
            )
        ]
    )
    rate = out.split("·")[1].split()[0] if "·" in out else out
    assert rate.rstrip("%") not in ("100", "100.0", "0", "0.0"), f"rendered {rate!r}"


def _warned(rules, records=4, passed=4):
    return ActionTally(
        action="warned", records=records, records_passed=passed, rules=rules, records_total=records
    )


def _heading(out: str) -> str:
    return next(line for line in out.splitlines() if line.lstrip().startswith("warned  ")).strip()


def test_heading_names_a_failed_warn_rule(render):
    rule = RuleTally(id="never_matches_warn", type="matches_regex", severity="warn", failed=4)

    out = render([_warned((rule,))], asked_for=("warned",))

    assert _heading(out) == (
        "warned  4/4 records passed · 100%  "
        "⚠ 1 non-blocking rule failed: never_matches_warn (warn) 4/4"
    )


def test_heading_with_no_non_blocking_failure_is_unchanged(render):
    rules = (
        RuleTally(id="soft", type="matches_regex", severity="warn", passed=4),
        RuleTally(id="hard", type="not_null", severity="error", passed=3, failed=1),
    )

    out = render([_warned(rules, passed=3)], asked_for=("warned",))

    assert _heading(out) == "warned  3/4 records passed · 75%"


def test_an_info_rule_counts_and_the_count_is_failed_over_checked(render):
    rules = (
        RuleTally(id="a_warn", type="matches_regex", severity="warn", passed=1, failed=3),
        RuleTally(id="an_info", type="matches_regex", severity="info", passed=2, failed=2),
    )

    out = render([_warned(rules)], asked_for=("warned",))

    assert _heading(out).endswith(
        "⚠ 2 non-blocking rules failed: a_warn (warn) 3/4, an_info (info) 2/4"
    )


def test_many_failed_warn_rules_are_named_and_counted(render):
    rules = tuple(
        RuleTally(id=f"w{n}", type="matches_regex", severity="warn", passed=n, failed=7 - n)
        for n in range(7)
    )

    out = render([_warned(rules, records=7, passed=7)], asked_for=("warned",))

    assert _heading(out).endswith(
        "⚠ 7 non-blocking rules failed: w0 (warn) 7/7, w1 (warn) 6/7, w2 (warn) 5/7, "
        "w3 (warn) 4/7, w4 (warn) 3/7 and 2 more"
    )


def test_the_note_comes_before_the_no_verdict_note(render):
    rule = RuleTally(id="soft", type="matches_regex", severity="warn", failed=4)
    tally = ActionTally(
        action="warned", records=4, records_passed=4, rules=(rule,), records_total=6
    )

    heading = _heading(render([tally], asked_for=("warned",)))

    assert heading.index("non-blocking rule failed") < heading.index("carried no verdict")


def test_json_is_unchanged():
    from agent_actions.cli.expect import _tally_row

    rule = RuleTally(id="never_matches_warn", type="matches_regex", severity="warn", failed=4)

    assert _tally_row(_warned((rule,))) == {
        "action": "warned",
        "records": 4,
        "records_passed": 4,
        "records_total": 4,
        "unverified": 0,
        "pass_rate": 1.0,
        "rules": [
            {
                "id": "never_matches_warn",
                "type": "matches_regex",
                "severity": "warn",
                "passed": 0,
                "failed": 4,
                "skipped": 0,
                "pass_rate": 0.0,
            }
        ],
    }
