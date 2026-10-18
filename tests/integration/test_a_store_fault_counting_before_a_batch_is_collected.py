"""A store error counting a batch action's rows before its batch is checked fails it (1524).

The run that checks a submitted batch counts the action's rows before it collects them.
An error there ended the run from outside the action's handler, so only the run-level
sweep recorded it: the action had no failure in the run history. It is now recorded where
it happens, as a store error counting an online action's rows before it runs is (1514).

Each run is its own ``agac`` process against the agac provider mock. Only the fault is
stood in for: the store raising on `finalize`'s first count in the checking run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_retry_answers_what_a_split_writes_below_it import (
    WORKFLOW,
    _project,
    _rows,
)

FAULT = "pre_count_fault.txt"
ERROR = "disk I/O error"

STAND_IN = f"""
import sqlite3
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

rows_collected = SQLiteBackend.rows_collected


def counting(self, action_name):
    if action_name == "finalize" and Path({FAULT!r}).exists():
        raise sqlite3.OperationalError({ERROR!r})
    return rows_collected(self, action_name)


SQLiteBackend.rows_collected = counting
"""


def _agac(project: Path, *args: str):
    result = run_agac(
        project,
        *args,
        env={
            "PYTHONPATH": str(project.parent / "pre_count_site"),
            "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0",
        },
    )
    return result.returncode, result.stdout + result.stderr


def _status(project: Path) -> dict:
    path = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())


def _last_run(project: Path) -> dict:
    executions = json.loads((project / "artefact" / "runs.json").read_text())["executions"]
    return max(executions, key=lambda run: run["started_at"])


def _faulted_check(tmp_path: Path, execution: str) -> tuple[Path, str]:
    project = _project(tmp_path, "batch")
    site = project.parent / "pre_count_site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(STAND_IN)
    code, output = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert code == 0, output
    assert _status(project)["finalize"]["status"] == "batch_submitted", output

    (project / FAULT).write_text("")
    code, output = _agac(project, "run", "-a", WORKFLOW, "-e", execution)
    (project / FAULT).unlink()
    assert code != 0 and ERROR in output, output
    return project, output


@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_the_action_is_failed_with_its_error(tmp_path, execution):
    project, output = _faulted_check(tmp_path, execution)

    entry = _status(project)["finalize"]
    assert entry["status"] == "failed", (entry, output)
    assert ERROR in entry.get("error_message", ""), (entry, output)


@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_the_run_history_records_the_action_failed_with_its_error(tmp_path, execution):
    project, output = _faulted_check(tmp_path, execution)

    run = _last_run(project)
    entry = run["actions"].get("finalize", {})
    assert entry.get("status") == "failed", (run, output)
    assert ERROR in entry.get("error", ""), (run, output)
    assert run["failed_actions"] == 1, run


def test_status_shows_the_failed_action_with_its_error(tmp_path):
    project, _ = _faulted_check(tmp_path, "sequential")

    code, output = _agac(project, "status", "-a", WORKFLOW)

    assert code == 0, output
    (line,) = [line for line in output.splitlines() if " finalize " in line]
    assert "failed" in line and ERROR in line, output


def test_the_next_run_collects_the_batch_it_submitted(tmp_path):
    project, _ = _faulted_check(tmp_path, "sequential")
    batches = sorted((project / ".agac" / "batch_state").glob("*.json"))

    code, output = _agac(project, "run", "-a", WORKFLOW)
    if "run again" in output.lower():
        code, more = _agac(project, "run", "-a", WORKFLOW)
        output += more

    assert code == 0, output
    assert sorted((project / ".agac" / "batch_state").glob("*.json")) == batches, output
    assert _status(project)["finalize"]["status"] == "completed", output
    rows = _rows(project, "finalize", "pages1.json") + _rows(project, "finalize", "pages2.json")
    assert [row["_state"] for row in rows] == ["processed"] * 8, output
