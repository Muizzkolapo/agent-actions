"""`agac status --json` prints each action's status and the run's, as one document.

The run status is the one `agac run` and `agac retry` end with for the same action
statuses. Scripts read the keys, so the exact set is pinned here.
"""

from __future__ import annotations

import itertools
import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.exit_codes import run_status
from agent_actions.cli.main import cli
from agent_actions.cli.status import status_report
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

WORKFLOW = "wf"


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    workflow = tmp_path / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(f"name: {WORKFLOW}\nactions: []\n")
    (workflow / "agent_io").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _store(project, statuses: dict) -> None:
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    status_file.write_text(json.dumps(statuses))


def _status_json(*args: str):
    return CliRunner().invoke(cli, ["status", "-w", WORKFLOW, "--json", *args])


def test_the_document_holds_exactly_these_keys(project):
    _store(
        project,
        {
            "extract": {"status": "completed", "record_limit": 5},
            "summarize": {"status": "failed", "error_message": "boom\nTraceback: ..."},
        },
    )

    result = _status_json()

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "workflow": WORKFLOW,
        "run_status": "FAILED",
        "actions": [
            {"name": "extract", "status": "completed", "error": None},
            {"name": "summarize", "status": "failed", "error": "boom\nTraceback: ..."},
        ],
    }
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("statuses", "run_status"),
    [
        (["completed", "completed"], "SUCCESS"),
        (["completed", "completed_with_failures"], "SUCCESS"),
        (["completed", "skipped"], "SUCCESS"),
        (["completed", "failed"], "FAILED"),
        (["failed", "skipped"], "FAILED"),
        (["completed", "running"], "PAUSED"),
        (["completed", "batch_submitted"], "PAUSED"),
        (["failed", "pending"], "PAUSED"),
    ],
)
def test_the_run_status_is_the_one_a_run_ends_with(project, statuses, run_status):
    _store(project, {f"a{n}": {"status": status} for n, status in enumerate(statuses)})

    report = json.loads(_status_json().stdout)

    assert report["run_status"] == run_status
    assert [action["status"] for action in report["actions"]] == statuses


@pytest.mark.parametrize(
    "statuses",
    [
        *([status.value] for status in ActionStatus),
        *([a.value, b.value] for a, b in itertools.combinations(ActionStatus, 2)),
    ],
    ids="+".join,
)
def test_the_run_status_agrees_with_retry_over_every_pair_of_statuses(project, statuses):
    stored = {f"a{n}": {"status": status} for n, status in enumerate(statuses)}
    _store(project, stored)
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"

    report = status_report(WORKFLOW, project)

    assert report["run_status"] == run_status(ActionStateManager(status_file, list(stored)))


def test_a_workflow_that_never_ran_has_no_run_status_and_says_so_on_stderr(project):
    result = _status_json()

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"workflow": WORKFLOW, "run_status": None, "actions": []}
    assert "No action status is stored for workflow 'wf'" in result.stderr


def test_an_error_is_reported_only_for_a_failed_action(project):
    _store(project, {"extract": {"status": "completed", "error_message": "stale"}})

    (action,) = json.loads(_status_json().stdout)["actions"]

    assert action == {"name": "extract", "status": "completed", "error": None}


def test_the_table_is_printed_without_json(project):
    _store(project, {"extract": {"status": "completed"}})

    result = CliRunner().invoke(cli, ["status", "-w", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert "Workflow Status for wf" in result.stdout
    assert "extract" in result.stdout and "completed" in result.stdout
