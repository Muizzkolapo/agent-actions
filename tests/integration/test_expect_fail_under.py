"""`--fail-under` turns stored verdicts into a CI exit code.

Without it expectations annotate a run; with it they gate one.
"""

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "inline_rules"


def _record(passed):
    outcome = {
        "id": "len",
        "type": "not_null",
        "severity": "error",
        "passed": passed,
        "detail": "",
        "definition_hash": "hash",
        "skipped": False,
    }
    return {
        "summary": "text",
        "_state": "processed",
        "expect": {
            "overall_pass": passed,
            "failed": [] if passed else ["len"],
            "skipped": [],
            "outcomes": [outcome],
        },
    }


def _project(tmp_path, verdicts):
    """A project whose store holds one record per entry in *verdicts*."""
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root)
    if verdicts:
        paths = ProjectPathsFactory.create_project_paths(
            WORKFLOW, WORKFLOW, auto_create=True, project_root=root
        )
        backend = get_storage_backend(
            workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW
        )
        backend.initialize()
        backend.write_target(
            "summarize", "verdicts.json", [_record(p) for p in verdicts], force_full=True
        )
        backend.close()
    return root


@pytest.fixture
def gate(tmp_path, monkeypatch):
    def _gate(verdicts, *args):
        monkeypatch.chdir(_project(tmp_path, verdicts))
        return CliRunner().invoke(cli, ["expect", "report", "-a", WORKFLOW, *args])

    return _gate


def test_a_pass_rate_above_the_threshold_exits_zero(gate):
    result = gate([True, True, False], "--fail-under", "50")
    assert result.exit_code == 0, result.output


def test_a_pass_rate_below_the_threshold_exits_nonzero(gate):
    result = gate([True, False, False], "--fail-under", "50")
    assert result.exit_code != 0
    assert "summarize" in result.output


def test_a_pass_rate_exactly_at_the_threshold_is_not_under_it(gate):
    result = gate([True, False], "--fail-under", "50")
    assert result.exit_code == 0, result.output


def test_the_failure_names_the_rate_that_fell_short(gate):
    result = gate([True, False, False], "--fail-under", "90")
    assert "33" in result.output, result.output


def test_a_store_with_no_verdicts_fails_the_gate(gate):
    """A gate that passes because nothing ran is not a gate."""
    result = gate([], "--fail-under", "50")
    assert result.exit_code != 0, result.output


def test_without_the_flag_an_empty_store_is_not_an_error(gate):
    assert gate([]).exit_code == 0


def test_without_the_flag_a_failing_rate_still_exits_zero(gate):
    """The report annotates unless asked to gate."""
    assert gate([False, False]).exit_code == 0


def test_a_threshold_of_zero_passes_whenever_anything_ran(gate):
    assert gate([False, False], "--fail-under", "0").exit_code == 0


def test_a_threshold_above_a_hundred_is_refused(gate):
    result = gate([True], "--fail-under", "150")
    assert result.exit_code != 0
    assert "150" in result.output


def test_the_json_report_is_still_emitted_when_the_gate_fails(gate):
    import json

    result = gate([False, False], "--fail-under", "50", "--json")
    assert result.exit_code != 0
    assert json.loads(result.stdout)["actions"], "the gate swallowed the report it gated on"
