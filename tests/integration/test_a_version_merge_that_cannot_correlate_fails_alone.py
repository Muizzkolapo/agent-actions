"""A version merge that cannot correlate its versions fails as an action does (1478).

The merge's versions were read and aligned outside the handler every other action
failure goes through. A store error while reading them, or version records that
cannot be aligned, ended a sequential run at once, leaving every branch that does not
read the merge pending. A parallel run caught the error but left the merge `running`,
so its reader ran against a merge that had stored nothing and failed on that instead
of being skipped.

Every run is its own `agac` process. Only the fault is stood in for: the store
raising while the merge reads a version's target, or a version record coming back
without the id the merge aligns versions on.
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
MERGE = "merge_direct"
READER = "fanin_asymmetric"
NOT_BELOW_THE_MERGE = [
    "plain_note",
    "merge_votes",
    "fanin_consumer",
    "unequal_diamond",
    "reduce_summary",
]
FAULT = "fault.txt"

# Reads of a version target raise while the fault file exists; what it holds
# says how: the store's own error, or a record that cannot be aligned.
STAND_IN = f"""
import sqlite3
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

read_target = SQLiteBackend.read_target


def reading(self, action_name, relative_path):
    rows = read_target(self, action_name, relative_path)
    fault = Path({FAULT!r})
    if not action_name.startswith("vote_direct_") or not fault.exists():
        return rows
    if fault.read_text() == "store":
        raise sqlite3.OperationalError("disk I/O error")
    for row in rows:
        row.pop("version_correlation_id", None)
    return rows


SQLiteBackend.read_target = reading
"""

FAULTS = {
    "store": "disk I/O error",
    "unaligned": "Could not align versions",
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
def test_the_merge_fails_its_reader_is_skipped_and_the_other_branches_finish(
    project, execution, fault
):
    root, stand_in = project
    (root / FAULT).write_text(fault)

    result = _agac(root, stand_in, "run", "-a", WORKFLOW, "--fresh", "--execution-mode", execution)
    output = result.stdout + result.stderr

    assert FAULTS[fault] in output, output
    statuses = _statuses(root)
    assert statuses[MERGE] == "failed", (statuses, output)
    assert statuses[READER] == "skipped", (statuses, output)
    for action in NOT_BELOW_THE_MERGE:
        assert statuses[action] == "completed", (action, statuses, output)
    assert _rows(root, MERGE) == []
    assert _rows(root, READER) == []
    assert result.returncode != 0, output


@pytest.mark.parametrize("recover", ["run", "retry"])
def test_once_the_fault_clears_the_merge_and_its_reader_answer_every_record(project, recover):
    root, stand_in = project
    (root / FAULT).write_text("store")
    _agac(root, stand_in, "run", "-a", WORKFLOW, "--fresh")
    (root / FAULT).unlink()

    result = _agac(root, stand_in, recover, "-a", WORKFLOW)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert set(_statuses(root).values()) == {"completed"}, (_statuses(root), output)
    merged = _rows(root, MERGE)
    assert len(merged) == 3
    assert all("decision" in row["content"][MERGE] for row in merged)
    read = _rows(root, READER)
    assert len(read) == 3
    assert all(row["content"][READER]["both_branches"] for row in read)
