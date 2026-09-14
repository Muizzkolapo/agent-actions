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


MULTI = "shared_suite"


def _record(passed, action="summarize"):
    outcome = {
        "id": "len",
        "type": "not_null",
        "severity": "error",
        "passed": passed,
        "detail": "",
        "definition_hash": "hash",
        "skipped": False,
    }
    # Namespaced under the action, the way target storage holds a record.
    return {
        "_state": "processed",
        "source_guid": "guid",
        "content": {
            action: {
                "summary": "text",
                "expect": {
                    "overall_pass": passed,
                    "failed": [] if passed else ["len"],
                    "skipped": [],
                    "outcomes": [outcome],
                },
            }
        },
    }


def _multi_project(tmp_path, stored):
    """A two-action project; *stored* maps an action to the verdicts it wrote."""
    root = tmp_path / "multi"
    shutil.copytree(SOURCE, root)
    paths = ProjectPathsFactory.create_project_paths(
        MULTI, MULTI, auto_create=True, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=MULTI)
    backend.initialize()
    for action, verdicts in stored.items():
        backend.write_target(
            action,
            "verdicts.json",
            [_record(p, action=action) for p in verdicts],
            force_full=True,
        )
    backend.close()
    return root


@pytest.fixture
def multi_gate(tmp_path, monkeypatch):
    def _gate(stored, *args):
        monkeypatch.chdir(_multi_project(tmp_path, stored))
        return CliRunner().invoke(cli, ["expect", "report", "-a", MULTI, *args])

    return _gate


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


def test_one_failing_action_fails_the_gate_even_when_another_is_perfect(multi_gate):
    """Per action, not pooled: pooling lets a healthy action carry a broken one."""
    result = multi_gate(
        {"summarize": [True, True, True, True], "resummarize": [False, False]}, "--fail-under", "60"
    )
    assert result.exit_code != 0, result.output
    assert "resummarize" in result.stderr, result.stderr
    # Pooled would be 4/6 = 67%, over the threshold, and would have exited zero.


def test_an_action_that_declares_expectations_but_stored_none_fails_the_gate(multi_gate):
    """Half a workflow unverified is the CI regression the gate exists to catch."""
    result = multi_gate({"summarize": [True, True, True]}, "--fail-under", "95")
    assert result.exit_code != 0, result.output
    assert "resummarize" in result.stderr, result.stderr


def test_a_rate_exactly_at_the_threshold_survives_float_arithmetic(multi_gate):
    """29/50 is exactly 58%, but 29 / 50 * 100 is 57.99999999999999."""
    verdicts = [True] * 29 + [False] * 21
    result = multi_gate({"summarize": verdicts, "resummarize": [True]}, "--fail-under", "58")
    assert result.exit_code == 0, result.output


def test_the_failure_names_the_action_that_fell_short(multi_gate):
    result = multi_gate({"summarize": [True], "resummarize": [False, False]}, "--fail-under", "90")
    assert "resummarize" in result.stderr, result.stderr
    assert "0/2" in result.stderr, "the gate did not name the counts behind the rate"


def test_the_gate_message_does_not_round_a_shortfall_into_the_threshold(multi_gate):
    """949/1000 is 94.9%; reported as '95%' the message contradicts itself."""
    verdicts = [True] * 949 + [False] * 51
    result = multi_gate({"summarize": verdicts, "resummarize": [True]}, "--fail-under", "95")
    assert result.exit_code != 0
    assert "95%: summarize 95%" not in result.stderr, result.stderr


def test_gating_one_action_names_that_action_when_it_stored_nothing(multi_gate):
    """The workflow has verdicts; the filtered action does not. Say which."""
    result = multi_gate(
        {"summarize": [True, True]}, "--action", "resummarize", "--fail-under", "50"
    )
    assert result.exit_code != 0
    assert "resummarize" in result.stderr, result.stderr


def _no_verdict_record(action="summarize"):
    """A record the action produced output for but wrote no verdict on."""
    return {
        "_state": "exhausted",
        "source_guid": "guid",
        "content": {action: {"summary": "tombstoned"}},
    }


def test_records_the_action_could_not_rate_fail_the_gate(tmp_path, monkeypatch):
    """Rating only the survivors of a run that tombstoned records reports them
    at full health; the gate must not accept a denominator that excludes them."""
    root = tmp_path / "partial"
    shutil.copytree(SOURCE, root)
    paths = ProjectPathsFactory.create_project_paths(
        MULTI, MULTI, auto_create=True, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=MULTI)
    backend.initialize()
    backend.write_target(
        "summarize",
        "verdicts.json",
        [_record(True), _record(True), _no_verdict_record(), _no_verdict_record()],
        force_full=True,
    )
    backend.write_target(
        "resummarize", "verdicts.json", [_record(True, action="resummarize")], force_full=True
    )
    backend.close()
    monkeypatch.chdir(root)

    result = CliRunner().invoke(cli, ["expect", "report", "-a", MULTI, "--fail-under", "95"])
    assert result.exit_code != 0, result.output
    assert "2" in result.stderr and "summarize" in result.stderr, result.stderr
