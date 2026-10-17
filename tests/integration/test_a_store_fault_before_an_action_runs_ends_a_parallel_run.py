"""A store error before an action's work begins ends a parallel run, as it ends a sequential one (1508).

Setting an action running, and counting the rows it holds before it runs, sit outside
the handler that fails an action: the store is not answering, and a run that went on
would read and write through it. A sequential run ended there. A parallel run running
several actions at once caught the error, logged it and went on: the action was left
`running` (or `pending`), the actions reading it ran against a target it never wrote
and failed on that instead, and the run ended "paused … Run again to continue" with
exit 0.

Every run is its own `agac` process. Only the fault is stood in for: the store raising
for one action of a level that runs four, either clearing that action's node-level
disposition as its work starts, or counting its rows before it runs.
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
# The other actions of the faulted action's level, which run beside it.
BESIDE = ["split_words", "vote_direct_1", "vote_direct_2"]
# Every action of a later level: none should run once the store has failed.
LATER = [
    "vote_1",
    "vote_2",
    "plain_note",
    "merge_votes",
    "merge_direct",
    "fanin_consumer",
    "fanin_asymmetric",
    "unequal_diamond",
    "reduce_summary",
]
FAULT = "fault.txt"

STAND_IN = f"""
import sqlite3
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

rows_collected = SQLiteBackend.rows_collected
clear_disposition = SQLiteBackend.clear_disposition


def _faulted(action_name, route):
    fault = Path({FAULT!r})
    return action_name == {FAULTED!r} and fault.exists() and fault.read_text() == route


def counting(self, action_name):
    if _faulted(action_name, "count"):
        raise sqlite3.OperationalError("disk I/O error")
    return rows_collected(self, action_name)


def clearing(self, action_name, disposition=None, record_id=None):
    if record_id is not None and _faulted(action_name, "start"):
        raise sqlite3.OperationalError("database is locked")
    return clear_disposition(self, action_name, disposition, record_id)


SQLiteBackend.rows_collected = counting
SQLiteBackend.clear_disposition = clearing
"""

# What each route leaves the faulted action as: counting fails an action already
# set running; a failed start never set it running.
FAULTS = {
    "count": ("disk I/O error", "failed"),
    "start": ("database is locked", "pending"),
}


def _workflow(root):
    return root / "agent_workflow" / WORKFLOW


def _statuses(root):
    path = _workflow(root) / "agent_io" / ".agent_status.json"
    return {name: entry["status"] for name, entry in json.loads(path.read_text()).items()}


def _rows(root, action):
    backend = get_storage_backend(workflow_path=str(_workflow(root)), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
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


@pytest.mark.parametrize("fault", sorted(FAULTS))
@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_the_run_ends_failed_and_nothing_below_the_fault_runs(project, execution, fault):
    root, stand_in = project
    (root / FAULT).write_text(fault)
    error, left_as = FAULTS[fault]

    result = _agac(root, stand_in, "run", "-a", WORKFLOW, "--fresh", "--execution-mode", execution)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert error in output, output
    assert "Run again to continue" not in output, output
    statuses = _statuses(root)
    assert "running" not in statuses.values(), (statuses, output)
    assert statuses[FAULTED] == left_as, (statuses, output)
    for action in BESIDE:
        assert statuses[action] == "completed", (action, statuses, output)
    for action in LATER:
        assert statuses[action] == "pending", (action, statuses, output)
    assert _rows(root, FAULTED) == []
    assert _rows(root, READER) == []


@pytest.mark.parametrize("execution", ["parallel", "sequential"])
def test_once_the_fault_clears_a_run_answers_every_record(project, execution):
    root, stand_in = project
    (root / FAULT).write_text("count")
    _agac(root, stand_in, "run", "-a", WORKFLOW, "--fresh", "--execution-mode", execution)
    (root / FAULT).unlink()

    # The faulted action failed with no failed record: retry has nothing to
    # repair and says so, rather than reporting success.
    refused = _agac(root, stand_in, "retry", "-a", WORKFLOW)
    assert refused.returncode != 0, refused.stdout + refused.stderr
    assert f"agac run -a {WORKFLOW}" in refused.stdout + refused.stderr

    result = _agac(root, stand_in, "run", "-a", WORKFLOW, "--execution-mode", execution)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert set(_statuses(root).values()) == {"completed"}, (_statuses(root), output)
    assert len(_rows(root, FAULTED)) == 3
    read = _rows(root, READER)
    assert len(read) == 3
    assert all(row["content"][READER]["both_branches"] for row in read)
