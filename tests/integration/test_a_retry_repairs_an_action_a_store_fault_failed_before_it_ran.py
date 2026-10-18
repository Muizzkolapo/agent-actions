"""A retry repairs an action a store fault failed before any of its records ran (1514).

Setting an action running and counting the rows it holds before it runs sit outside
the handler that fails an action, and a store error there ends the run. The action that
raised was left with no failure the store holds, since the store was not answering, and
with nothing in its status to say why: counting left it ``failed`` with no error message,
and a failed start left it ``pending``. ``agac retry`` then refused ("No failed record is
recorded …") or, for the failed start, reported nothing to retry.

An action that failed as a whole is what a retry re-runs in full, so once the fault
clears ``agac retry`` re-runs it and every action after it, as it does for any failure
that is the action's own.

Counting its rows once it has run sits outside that handler too. A store error there left
the action ``completed`` with its readers pending, so ``agac retry`` said "Nothing to
retry" and exited 0 (1519). It is now failed with its error, as a fault before it ran is.
Each route's failure is in the run history and in ``agac status`` as well.

Every run is its own ``agac`` process. Only the fault is stood in for: the store raising
for one action of a level that runs four.
"""

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
FAULTED = "note_direct"
READER = "fanin_asymmetric"
FAULT = "fault.txt"

STAND_IN = f"""
import sqlite3
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

rows_collected = SQLiteBackend.rows_collected
clear_disposition = SQLiteBackend.clear_disposition
_counted = {{}}


def _faulted(action_name, route):
    fault = Path({FAULT!r})
    return action_name == {FAULTED!r} and fault.exists() and fault.read_text() == route


def counting(self, action_name):
    _counted[action_name] = _counted.get(action_name, 0) + 1
    if _faulted(action_name, "count"):
        raise sqlite3.OperationalError("disk I/O error")
    if _faulted(action_name, "after") and _counted[action_name] > 1:
        raise sqlite3.OperationalError("database or disk is full")
    return rows_collected(self, action_name)


def clearing(self, action_name, disposition=None, record_id=None):
    if record_id is not None and _faulted(action_name, "start"):
        raise sqlite3.OperationalError("database is locked")
    return clear_disposition(self, action_name, disposition, record_id)


SQLiteBackend.rows_collected = counting
SQLiteBackend.clear_disposition = clearing
"""

# The error each route raises: counting the action's rows before it runs, clearing its
# node-level disposition as its work starts, and counting its rows once it has run.
FAULTS = {
    "after": "database or disk is full",
    "count": "disk I/O error",
    "start": "database is locked",
}


def _workflow(root):
    return root / "agent_workflow" / WORKFLOW


def _status_file(root):
    return json.loads((_workflow(root) / "agent_io" / ".agent_status.json").read_text())


def _statuses(root):
    return {name: entry["status"] for name, entry in _status_file(root).items()}


def _backend(root):
    backend = get_storage_backend(workflow_path=str(_workflow(root)), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _rows(root, action):
    backend = _backend(root)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _dispositions(root, action):
    backend = _backend(root)
    try:
        return backend.get_disposition(action)
    finally:
        backend.close()


def _agac(root, stand_in, *args):
    return run_agac(root, *args, env={"PYTHONPATH": str(stand_in), "COLUMNS": "240"})


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    stand_in = tmp_path / "stand_in"
    stand_in.mkdir()
    (stand_in / "sitecustomize.py").write_text(STAND_IN)
    return root, stand_in


def _fail_the_run(root, stand_in, execution, fault):
    (root / FAULT).write_text(fault)
    result = _agac(root, stand_in, "run", "-a", WORKFLOW, "--fresh", "--execution-mode", execution)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert FAULTS[fault] in output, output
    (root / FAULT).unlink()
    return output


@pytest.mark.parametrize("fault", sorted(FAULTS))
@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_the_action_that_raised_is_recorded_failed_with_its_error(project, execution, fault):
    root, stand_in = project
    output = _fail_the_run(root, stand_in, execution, fault)

    entry = _status_file(root)[FAULTED]
    assert entry["status"] == "failed", (entry, output)
    assert FAULTS[fault] in entry.get("error_message", ""), (entry, output)


@pytest.mark.parametrize("fault", sorted(FAULTS))
@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_once_the_fault_clears_a_retry_reruns_the_action_and_its_readers(project, execution, fault):
    root, stand_in = project
    _fail_the_run(root, stand_in, execution, fault)

    result = _agac(root, stand_in, "retry", "-a", WORKFLOW)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert FAULTED in output and FAULTS[fault] in output, output
    assert "Nothing to retry" not in output, output
    assert set(_statuses(root).values()) == {"completed"}, (_statuses(root), output)
    # The error was why it failed; completed, it no longer says it failed.
    assert "error_message" not in _status_file(root)[FAULTED]
    assert len(_rows(root, FAULTED)) == 3
    read = _rows(root, READER)
    assert len(read) == 3
    assert all(row["content"][READER]["both_branches"] for row in read)
    # Nothing the retry wrote down about the failure is left behind it.
    assert all(row["disposition"] != "failed" for row in _dispositions(root, FAULTED))


@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_a_dry_run_names_the_action_and_its_error_and_changes_nothing(project, execution):
    root, stand_in = project
    _fail_the_run(root, stand_in, execution, "count")
    before = _status_file(root)

    result = _agac(root, stand_in, "retry", "-a", WORKFLOW, "--dry-run")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert FAULTED in output and FAULTS["count"] in output, output
    assert "Dry run" in output, output
    assert _status_file(root) == before
    assert _dispositions(root, FAULTED) == []


@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_after_a_fault_counting_its_rows_nothing_reads_what_it_stored(project, execution):
    """Failed, the action is re-run by the retry before any action reads it."""
    root, stand_in = project
    output = _fail_the_run(root, stand_in, execution, "after")

    statuses = _statuses(root)
    assert statuses[FAULTED] == "failed", (statuses, output)
    assert statuses[READER] == "pending", (statuses, output)


def _last_run(root):
    return json.loads((root / "artefact" / "runs.json").read_text())["executions"][-1]


@pytest.mark.parametrize("fault", sorted(FAULTS))
@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_the_run_history_records_the_action_failed_with_its_error(project, execution, fault):
    root, stand_in = project
    output = _fail_the_run(root, stand_in, execution, fault)

    run = _last_run(root)
    entry = run["actions"].get(FAULTED, {})
    assert entry.get("status") == "failed", (run, output)
    assert FAULTS[fault] in entry.get("error", ""), (run, output)
    assert run["failed_actions"] == 1, run


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_status_shows_the_failed_action_with_its_error(project, fault):
    root, stand_in = project
    _fail_the_run(root, stand_in, "parallel", fault)

    result = _agac(root, stand_in, "status", "-a", WORKFLOW)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    (line,) = [line for line in output.splitlines() if f" {FAULTED} " in line]
    assert "failed" in line and FAULTS[fault] in line, output
