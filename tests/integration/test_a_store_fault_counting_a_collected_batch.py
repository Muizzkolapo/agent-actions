"""A store error counting a batch action's rows once its batch is collected fails it (1519).

The run that collects a batch counts the action's rows before and after it writes them.
A store error in the count after left the action ``completed`` with the run failed, so
``agac retry`` said "Nothing to retry". The action is now failed with that error, and
``agac retry`` re-runs it.

Each run is its own ``agac`` process against the agac provider mock. Only the fault is
stood in for: the store raising on the second count of `finalize` in one process.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests._support.agac_cli import run_agac
from tests.integration.test_a_retry_answers_what_a_split_writes_below_it import (
    WORKFLOW,
    _project,
    _rows,
)

FAULT = "count_fault.txt"
ERROR = "database or disk is full"

STAND_IN = f"""
import sqlite3
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

rows_collected = SQLiteBackend.rows_collected
_counted = {{}}


def counting(self, action_name):
    _counted[action_name] = _counted.get(action_name, 0) + 1
    if action_name == "finalize" and Path({FAULT!r}).exists() and _counted[action_name] > 1:
        raise sqlite3.OperationalError({ERROR!r})
    return rows_collected(self, action_name)


SQLiteBackend.rows_collected = counting
"""


def _agac(project: Path, stand_in: Path, *args: str):
    result = run_agac(
        project,
        *args,
        env={"PYTHONPATH": str(stand_in), "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    return result.returncode, result.stdout + result.stderr


def _status(project: Path) -> dict:
    path = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())


def _faulted_collect(tmp_path: Path) -> tuple[Path, Path, str]:
    project = _project(tmp_path, "batch")
    stand_in = tmp_path / "stand_in"
    stand_in.mkdir()
    (stand_in / "sitecustomize.py").write_text(STAND_IN)
    code, output = _agac(project, stand_in, "run", "-a", WORKFLOW, "--fresh")
    assert code == 0, output
    assert _status(project)["finalize"]["status"] == "batch_submitted", output

    (project / FAULT).write_text("")
    code, output = _agac(project, stand_in, "run", "-a", WORKFLOW)
    (project / FAULT).unlink()
    assert code != 0 and ERROR in output, output
    return project, stand_in, output


def test_the_action_is_failed_with_its_error(tmp_path):
    project, _, output = _faulted_collect(tmp_path)

    entry = _status(project)["finalize"]
    assert entry["status"] == "failed", (entry, output)
    assert ERROR in entry.get("error_message", ""), (entry, output)


def test_a_retry_re_runs_it_and_it_completes(tmp_path):
    project, stand_in, _ = _faulted_collect(tmp_path)

    code, output = _agac(project, stand_in, "retry", "-a", WORKFLOW)
    assert code == 0, output
    assert "Nothing to retry" not in output, output
    assert "finalize" in output and ERROR in output, output
    code, collected = _agac(project, stand_in, "run", "-a", WORKFLOW)
    assert code == 0, collected

    assert {name: e["status"] for name, e in _status(project).items()} == {
        "flatten": "completed",
        "roll_up": "completed",
        "finalize": "completed",
    }, output + collected
    rows = _rows(project, "finalize", "pages1.json")
    assert [row["_state"] for row in rows] == ["processed"] * 4, output + collected
