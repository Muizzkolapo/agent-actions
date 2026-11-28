"""A staged file deleted while its batch is out leaves no disposition behind (#1939).

Its records are forgotten before the batch is collected; the collect then wrote a
disposition for each, and the pass that deletes the file kept them. An action then
counted, and `agac retry` could name, records no staged file holds.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_staged_input_change_and_fresh_while_a_batch_is_open import (
    WORKFLOW,
    _actions,
    _collect,
    _project,
    _run,
)


def _disposed(root, action: str) -> set[str]:
    """The record ids *action* holds a disposition for, read from the sandbox store."""
    store = root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.sandbox.db"
    with sqlite3.connect(store) as db:
        rows = db.execute(
            "SELECT record_id FROM record_disposition WHERE action_name = ?", (action,)
        ).fetchall()
    return {record_id for (record_id,) in rows}


def _records(root, action: str) -> set[str]:
    result = run_agac(
        root, "records", "-w", WORKFLOW, "--sandbox", "-A", action, "--field", "source_guid"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return set(json.loads(result.stdout))


@pytest.mark.parametrize("shape", ["tag_after_a_tool", "tag_first"])
def test_no_action_keeps_a_disposition_for_a_record_of_the_deleted_file(tmp_path, shape):
    root = _project(tmp_path, shape)
    code, output = _run(root)
    assert code == 4, output
    (root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "b.json").unlink()

    assert _collect(root)[-1] == 0

    for action in _actions(root):
        assert _disposed(root, action) == _records(root, action), action
