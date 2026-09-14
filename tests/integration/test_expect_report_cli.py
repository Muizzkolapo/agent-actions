"""`agac expect report` reads back the verdicts a run wrote.

Answers the question that otherwise means opening SQLite by hand: which rule
fails most often, and on which action.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.expectations.report import RuleTally, tally_action
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "inline_rules"


def _verdict(*outcomes):
    """A record's ``expect`` block, shaped as ``SuiteResult.to_record_dict`` writes it."""
    return {
        "overall_pass": not any(o["severity"] == "error" and not o["passed"] for o in outcomes),
        "failed": [o["id"] for o in outcomes if not o["passed"] and o["severity"] == "error"],
        "skipped": [
            o["id"]
            for o in outcomes
            if o.get("skipped") and not o["passed"] and o["severity"] == "error"
        ],
        "outcomes": list(outcomes),
    }


def _outcome(rule_id, passed, severity="error", skipped=False, rule_type="not_null"):
    return {
        "id": rule_id,
        "type": rule_type,
        "severity": severity,
        "passed": passed,
        "detail": "",
        "definition_hash": "hash",
        "skipped": skipped,
    }


class TestTally:
    """The aggregation, independent of where the records came from."""

    def test_a_rule_is_counted_once_per_record_it_ran_on(self):
        records = [
            {"expect": _verdict(_outcome("len", passed=True))},
            {"expect": _verdict(_outcome("len", passed=False))},
            {"expect": _verdict(_outcome("len", passed=False))},
        ]
        tally = tally_action("summarize", records)
        assert tally.records == 3
        assert tally.records_passed == 1
        assert tally.rules == (
            RuleTally(id="len", type="not_null", severity="error", passed=1, failed=2, skipped=0),
        )

    def test_a_skipped_outcome_counts_as_neither_pass_nor_fail(self):
        records = [{"expect": _verdict(_outcome("tone", passed=False, skipped=True))}]
        rule = tally_action("summarize", records).rules[0]
        assert (rule.passed, rule.failed, rule.skipped) == (0, 0, 1)
        assert rule.checked == 0
        assert rule.pass_rate is None, "a rule that never ran has no pass rate"

    def test_a_warn_failure_does_not_fail_the_record(self):
        records = [{"expect": _verdict(_outcome("tone", passed=False, severity="warn"))}]
        tally = tally_action("summarize", records)
        assert tally.records_passed == 1
        assert tally.rules[0].failed == 1

    def test_records_without_a_verdict_are_not_counted(self):
        tally = tally_action("summarize", [{"summary": "no verdict here"}])
        assert tally is None, "an action that never ran expectations has nothing to report"

    def test_rules_are_ordered_by_how_often_they_fail(self):
        records = [
            {"expect": _verdict(_outcome("rare", passed=True), _outcome("common", passed=False))},
            {"expect": _verdict(_outcome("rare", passed=False), _outcome("common", passed=False))},
        ]
        assert [r.id for r in tally_action("s", records).rules] == ["common", "rare"]

    def test_the_action_pass_rate_is_over_records_not_rules(self):
        records = [
            {"expect": _verdict(_outcome("a", passed=True), _outcome("b", passed=True))},
            {"expect": _verdict(_outcome("a", passed=False), _outcome("b", passed=True))},
        ]
        assert tally_action("s", records).pass_rate == 0.5

    def test_an_empty_action_has_nothing_to_report(self):
        assert tally_action("s", []) is None


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """A copy of the author fixtures with verdicts already in the store."""
    root = tmp_path_factory.mktemp("expect_report") / "project"
    shutil.copytree(SOURCE, root)

    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=True, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    backend.write_target(
        "summarize",
        "verdicts.json",
        [
            {
                "summary": "one",
                "_state": "processed",
                "expect": _verdict(
                    _outcome("len", passed=True), _outcome("tone", passed=True, severity="warn")
                ),
            },
            {
                "summary": "two",
                "_state": "processed",
                "expect": _verdict(
                    _outcome("len", passed=False), _outcome("tone", passed=False, severity="warn")
                ),
            },
            {
                "summary": "three",
                "_state": "processed",
                "expect": _verdict(
                    _outcome("len", passed=False), _outcome("tone", passed=True, severity="warn")
                ),
            },
        ],
        force_full=True,
    )
    backend.close()
    return root


@pytest.fixture
def run(project, monkeypatch):
    monkeypatch.chdir(project)

    def _run(*args):
        return CliRunner().invoke(cli, ["expect", "report", "-a", WORKFLOW, *args])

    return _run


def test_the_report_counts_every_stored_verdict(run):
    result = run("--json")
    assert result.exit_code == 0, result.output

    payload = json.loads(result.stdout)
    summarize = next(a for a in payload["actions"] if a["action"] == "summarize")
    assert summarize["records"] == 3
    assert summarize["records_passed"] == 1

    by_id = {rule["id"]: rule for rule in summarize["rules"]}
    assert (by_id["len"]["passed"], by_id["len"]["failed"]) == (1, 2)
    assert (by_id["tone"]["passed"], by_id["tone"]["failed"]) == (2, 1)


def test_the_rendered_report_names_the_rule_that_fails_most(run):
    result = run()
    assert result.exit_code == 0, result.output
    assert "len" in result.stdout


def test_an_action_with_no_stored_verdicts_is_reported_as_such(run):
    result = run("--action", "flatten")
    assert "flatten" in result.output


def test_a_workflow_with_an_empty_store_says_so_rather_than_printing_nothing(tmp_path, monkeypatch):
    root = tmp_path / "empty"
    shutil.copytree(SOURCE, root)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(cli, ["expect", "report", "-a", WORKFLOW])
    assert result.exit_code == 0, result.output
    assert "no verdict" in result.output.lower() or "no stored" in result.output.lower()
