"""`agac sandbox check` reads a strict expectations file and compares it with a sandbox run.

The file states only what a sandbox run makes deterministic: the exit code, the counts of
the scenario line, and per action its status and record counts. A key the check does not
know is refused by name, as a scenario key is, so a typo cannot pass as a check that holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.cli.dispositions import COUNT_KEYS as DISPOSITION_COUNTS
from agent_actions.cli.exit_codes import EXIT_CODES
from agent_actions.cli.sandbox_check import (
    Actual,
    ExpectationsError,
    compare,
    expectations_path,
    load_expected,
    parse_expected,
    report,
)
from agent_actions.workflow.managers.state import ActionStatus

REPO = Path(__file__).resolve().parents[3]
ACTIONS = ["read_ticket", "classify"]


def _actual(**over) -> Actual:
    values = {
        "exit_code": 0,
        "scenario": {"errors": 8, "rules_broken": 4, "dropped": 2, "calls": 30},
        "statuses": {"read_ticket": "completed", "classify": "completed"},
        "counts": {
            "read_ticket": {"records": 5, "success": 5, "filtered": 0},
            "classify": {"records": 4, "success": 4, "filtered": 1},
        },
    }
    values.update(over)
    return Actual(**values)


def _rows(data: dict, actual: Actual | None = None):
    return compare(parse_expected(data, "sandbox_expected.yml"), actual or _actual(), ACTIONS)


def test_each_stated_value_is_one_row_in_the_order_of_the_file():
    rows = _rows(
        {
            "exit_code": 0,
            "scenario": {"errors": 8, "batch_results_dropped": 2},
            "actions": {"classify": {"status": "completed", "filtered": 1}},
        }
    )

    assert [(row.what, row.expected, row.actual) for row in rows] == [
        ("exit code", 0, 0),
        ("scenario errors", 8, 8),
        ("scenario batch_results_dropped", 2, 2),
        ("classify status", "completed", "completed"),
        ("classify filtered", 1, 1),
    ]
    assert all(row.holds for row in rows)


def test_a_value_that_differs_is_a_row_that_does_not_hold():
    rows = _rows({"actions": {"classify": {"filtered": 2}}})

    assert [(row.what, row.holds) for row in rows] == [("classify filtered", False)]


def test_a_count_the_store_does_not_hold_is_none_and_does_not_hold():
    rows = _rows({"actions": {"classify": {"deferred": 0}}})

    assert rows[0].actual is None
    assert not rows[0].holds


def test_no_scenario_line_makes_each_scenario_count_none():
    rows = _rows({"scenario": {"errors": 0}}, _actual(scenario=None))

    assert (rows[0].actual, rows[0].holds) == (None, False)


def test_an_action_the_workflow_does_not_have_is_refused():
    with pytest.raises(ExpectationsError, match="clasify is not an action of the workflow"):
        _rows({"actions": {"clasify": {"success": 4}}})


def test_a_run_that_wrote_no_result_is_one_row_that_does_not_hold_after_the_exit_code():
    actual = _actual(exit_code=1, wrote_result=False)

    rows = compare(
        parse_expected({"exit_code": 1, "actions": {"clasify": {"success": 4}}}, "f"),
        actual,
        [],
    )

    assert [(row.what, row.holds) for row in rows] == [("exit code", True), ("run", False)]
    assert rows[1].mismatch == "wrote no result (the run stopped with exit code 1)"


def test_a_run_that_wrote_no_result_fails_the_report(capsys):
    rows = compare(
        parse_expected({"exit_code": 1}, "f"), _actual(exit_code=1, wrote_result=False), []
    )

    code = report(rows, "wf", "f.yml")

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL: 1 of 2 expectations do not hold:" in out
    assert "  run: wrote no result (the run stopped with exit code 1)" in out


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"exit_code": 0, "exit": 0}, "unknown key 'exit'"),
        ({"scenario": {"errors": 1, "dropped": 0}}, "scenario: unknown key 'dropped'"),
        ({"actions": {"classify": {"sucess": 4}}}, "actions.classify: unknown key 'sucess'"),
        ({"actions": {"classify": {"status": "done"}}}, "'done' is not one of pending, running"),
        ({"actions": {"classify": {"success": -1}}}, "-1 is not a whole number 0 or more"),
        ({"actions": {"classify": {"success": True}}}, "True is not a whole number"),
        ({"actions": {"classify": {"success": "4"}}}, "'4' is not a whole number"),
        ({"exit_code": 1.5}, "exit_code: 1.5 is not a whole number"),
        ({"actions": ["classify"]}, "actions: must be a mapping"),
        ({"actions": {"classify": 4}}, "actions.classify: must be a mapping"),
        ({"actions": {"classify": None}}, "actions.classify: states no value"),
        ({"actions": {"classify": {}}}, "actions.classify: states no value"),
        ([], "the file must be a mapping"),
        ({}, "the file states no expectation"),
        (None, "the file must be a mapping"),
    ],
)
def test_a_file_the_check_cannot_follow_is_refused_by_name(data, message):
    with pytest.raises(ExpectationsError, match=message):
        parse_expected(data, "sandbox_expected.yml")


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(ExpectationsError, match="sandbox_expected.yml: no such file"):
        load_expected(tmp_path / "sandbox_expected.yml")


def test_a_file_that_is_not_yaml_is_refused(tmp_path):
    path = tmp_path / "sandbox_expected.yml"
    path.write_text("actions: [\n")

    with pytest.raises(ExpectationsError, match="not valid YAML"):
        load_expected(path)


def test_the_workflow_s_own_file_is_read_before_the_shared_one(tmp_path: Path):
    assert expectations_path(tmp_path, "wf", None) == tmp_path / "sandbox_expected.yml"

    (tmp_path / "sandbox_expected.wf.yml").write_text("exit_code: 0\n")

    assert expectations_path(tmp_path, "wf", None) == tmp_path / "sandbox_expected.wf.yml"
    assert expectations_path(tmp_path, "wf", "other.yml") == tmp_path / "other.yml"
    assert expectations_path(tmp_path, "wf", "/abs/x.yml") == Path("/abs/x.yml")


def test_the_report_passes_when_every_row_holds(capsys):
    code = report(_rows({"exit_code": 0, "scenario": {"errors": 8}}), "wf", "f.yml")

    out = capsys.readouterr().out
    assert code == 0
    assert "PASS: all 2 expectations hold." in out


def test_the_report_names_each_row_that_does_not_hold(capsys):
    rows = _rows({"exit_code": 3, "actions": {"classify": {"filtered": 2, "success": 4}}})

    code = report(rows, "wf", "f.yml")

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL: 2 of 3 expectations do not hold:" in out
    assert "  exit code: expected 3, got 0" in out
    assert "  classify filtered: expected 2, got 1" in out


# The values the file takes come from the code that makes them, so they cannot drift.


@pytest.mark.parametrize("status", [status.value for status in ActionStatus])
def test_each_action_status_the_state_manager_writes_is_accepted(status):
    expected = parse_expected({"actions": {"classify": {"status": status}}}, "f")

    assert expected.actions == {"classify": {"status": status}}


@pytest.mark.parametrize("key", ["records", "total", "sent_elsewhere", *DISPOSITION_COUNTS])
def test_each_count_of_agac_dispositions_is_accepted(key):
    expected = parse_expected({"actions": {"classify": {key: 0}}}, "f")

    assert expected.actions == {"classify": {key: 0}}


@pytest.mark.parametrize("code", sorted(set(EXIT_CODES.values())))
def test_each_exit_code_of_agac_run_is_accepted(code):
    assert parse_expected({"exit_code": code}, "f").exit_code == code


@pytest.mark.parametrize("code", [2, 6, 130])
def test_an_exit_code_agac_run_does_not_return_is_refused(code):
    with pytest.raises(ExpectationsError, match=f"exit_code: {code} is not an exit code of agac"):
        parse_expected({"exit_code": code}, "f")


def test_the_reference_lists_each_status_and_each_exit_code():
    page = (REPO / "docs.agent-actions/docs/reference/cli/sandbox.md").read_text()
    rows = {
        line.split("|")[1].strip(): line for line in page.splitlines() if line.startswith("| `")
    }

    statuses = rows["`actions.<action>.status`"]
    assert all(f"`{status.value}`" in statuses for status in ActionStatus), statuses
    codes = rows["`exit_code`"]
    listed = ", ".join(str(code) for code in sorted(set(EXIT_CODES.values())))
    assert listed in codes.replace(" or ", ", "), codes
