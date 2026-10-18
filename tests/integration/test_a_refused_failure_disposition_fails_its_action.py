"""Online, a failure whose disposition the store refuses fails the action (1534).

An online run collects each file, writes its records' dispositions in one transaction,
then stores the file. When the store refused that write, the run went on: the failed
record held no disposition at all, the run exited 0, and `agac retry` said "Nothing to
retry", so the failure was never repaired. Online stamps no `deferred` a later run could
settle from, as a batch does, so the store error fails the action, as any other store
error does: its status and the run history name the error, and `agac retry` re-runs the
action in full once the store answers.

Each run is its own `agac` process against local tools. Only the fault is stood in for:
the store refusing the action's record dispositions while a flag file exists.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_retry_answers_what_a_split_writes_below_it import (
    ALL_FINAL,
    WORKFLOW,
    _project,
    _rows,
)

FAULT = "refuse_dispositions.txt"
STORE_ERROR = "database or disk is full"

STAND_IN = f"""
import sqlite3
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

_write = SQLiteBackend.set_dispositions_batch


def refusing(self, rows):
    rows = list(rows)
    flag = Path({FAULT!r})
    if flag.exists() and any(row[0] == flag.read_text().strip() for row in rows):
        raise sqlite3.OperationalError({STORE_ERROR!r})
    return _write(self, rows)


SQLiteBackend.set_dispositions_batch = refusing
"""


def _agac(project: Path, *args: str) -> tuple[int, str]:
    result = run_agac(
        project, *args, env={"PYTHONPATH": str(project.parent / "refusing_store_site")}
    )
    return result.returncode, result.stdout + result.stderr


def _dispositions(project: Path, action: str) -> dict[str, str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return dict(
            con.execute(
                "select record_id, disposition from record_disposition "
                "where action_name = ? and record_id != '__node__'",
                (action,),
            ).fetchall()
        )
    finally:
        con.close()


def _status(project: Path) -> dict:
    path = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())


def _last_run(project: Path) -> dict:
    return json.loads((project / "artefact" / "runs.json").read_text())["executions"][-1]


def _final(project: Path) -> list[str]:
    rows = _rows(project, "finalize", "pages1.json") + _rows(project, "finalize", "pages2.json")
    return sorted(
        row["content"]["finalize"]["summary"]
        for row in rows
        if (row.get("content") or {}).get("finalize")
    )


@pytest.fixture(params=["flatten", "roll_up"], ids=["first-action", "below-the-first"])
def refused(request, tmp_path):
    """Alpha fails at the action, and the store refuses that action's dispositions."""
    action = request.param
    project = _project(tmp_path, "tool")
    site = project.parent / "refusing_store_site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(STAND_IN)
    (project / "FAIL_AT").write_text(action)
    (project / FAULT).write_text(action)
    code, output = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    (project / FAULT).unlink()
    (project / "FAIL_AT").unlink()
    return project, action, code, output


def test_the_run_fails_the_action_with_the_store_error(refused):
    project, action, code, output = refused

    assert code == 1, output
    status = _status(project)
    assert status[action]["status"] == "failed", output
    assert STORE_ERROR in status[action].get("error_message", ""), status[action]
    assert status["finalize"]["status"] != "completed", output


def test_the_run_history_records_the_action_failed_with_the_store_error(refused):
    project, action, code, output = refused

    run = _last_run(project)
    entry = run["actions"].get(action, {})
    assert entry.get("status") == "failed", (run, output)
    assert STORE_ERROR in entry.get("error", ""), run


def test_a_retry_repairs_the_record_the_store_could_not_mark(refused):
    project, action, code, output = refused

    planned, plan = _agac(project, "retry", "-a", WORKFLOW, "--dry-run")
    assert planned == 0, plan
    assert "Nothing to retry" not in plan, plan

    code, output = _agac(project, "retry", "-a", WORKFLOW)

    assert code == 0, output
    assert set(_dispositions(project, action).values()) == {"success"}, output
    assert len(_dispositions(project, action)) == 4, output
    assert _final(project) == sorted(
        ALL_FINAL
        + ["FINAL[Page gamma. #1]", "FINAL[Page gamma. #2]"]
        + ["FINAL[Page delta. #1]", "FINAL[Page delta. #2]"]
    ), output
    assert {entry["status"] for entry in _status(project).values()} == {"completed"}
