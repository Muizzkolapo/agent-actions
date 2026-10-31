"""A batch record whose terminal disposition the store refused is settled later (1524).

The run that collects a batch stores each record's row, then writes its disposition. When
the store refuses that write, the record keeps the ``deferred`` it was stamped with at
submission, and the run warns. Nothing settled it afterwards: ``agac run`` read the action
complete, and ``agac retry`` found nothing failed, so a failed record whose failure was lost
was never retried. Its batch is collected and its row is stored, so the next ``agac run`` or
``agac retry`` writes the disposition that row stands for, and submits nothing again.

Each run is its own ``agac`` process against the agac provider mock. Only the fault is
stood in for: the store refusing `finalize`'s dispositions in the collecting run, and the
provider leaving one record out of its results.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_retry_answers_what_a_split_writes_below_it import (
    WORKFLOW,
    _project,
    _rows,
)

FAULT = "disposition_fault.txt"

STAND_IN = f"""
import sqlite3
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

_write = SQLiteBackend.set_dispositions_batch


def refusing(self, rows):
    rows = list(rows)
    if Path({FAULT!r}).exists() and any(row[0] == "finalize" for row in rows):
        raise sqlite3.OperationalError("database or disk is full")
    return _write(self, rows)


SQLiteBackend.set_dispositions_batch = refusing
"""


def _agac(project: Path, *args: str) -> tuple[int, str]:
    result = run_agac(
        project,
        *args,
        env={
            "PYTHONPATH": str(project.parent / "lost_disposition_site"),
            "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0",
        },
    )
    return result.returncode, result.stdout + result.stderr


def _dispositions(project: Path) -> dict[str, str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return dict(
            con.execute(
                "select record_id, disposition from record_disposition "
                "where action_name = 'finalize' and record_id != '__node__'"
            ).fetchall()
        )
    finally:
        con.close()


def _status(project: Path) -> dict:
    path = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())["finalize"]


def _batches(project: Path) -> list[Path]:
    return sorted((project / ".agac" / "batch_state").glob("*.json"))


def _all_rows(project: Path) -> list[dict]:
    return _rows(project, "finalize", "pages1.json") + _rows(project, "finalize", "pages2.json")


def _left_out(project: Path) -> str:
    """Have the provider leave the first task of one batch out of its results."""
    state_file = _batches(project)[0]
    state = json.loads(state_file.read_text())
    dropped = state["tasks"].pop(0)
    state_file.write_text(json.dumps(state))
    return dropped["custom_id"]


def _collected_with_the_fault(tmp_path: Path, *, leave_one_out: bool = False) -> Path:
    project = _project(tmp_path, "batch")
    site = project.parent / "lost_disposition_site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(STAND_IN)
    code, output = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert code == 0 and _status(project)["status"] == "batch_submitted", output
    if leave_one_out:
        _left_out(project)

    (project / FAULT).write_text("")
    code, output = _agac(project, "run", "-a", WORKFLOW)
    (project / FAULT).unlink()
    assert code == 0, output
    assert set(_dispositions(project).values()) == {"deferred"}, output
    assert len(_dispositions(project)) == 8, output
    return project


def _failed_record(project: Path) -> str:
    (failed,) = [row["source_guid"] for row in _all_rows(project) if row["_state"] == "failed"]
    return failed


class TestEveryRecordAnswered:
    def test_the_next_run_settles_each_record_and_submits_nothing(self, tmp_path):
        project = _collected_with_the_fault(tmp_path)
        batches, rows = _batches(project), _all_rows(project)

        code, output = _agac(project, "run", "-a", WORKFLOW)

        assert code == 0, output
        assert sorted(_dispositions(project).values()) == ["success"] * 8, output
        assert _batches(project) == batches, output
        assert _all_rows(project) == rows
        assert _status(project)["status"] == "completed"

    def test_a_retry_settles_each_record_and_finds_nothing_to_retry(self, tmp_path):
        project = _collected_with_the_fault(tmp_path)
        batches = _batches(project)

        code, output = _agac(project, "retry", "-a", WORKFLOW)

        assert code == 0, output
        assert "Nothing to retry" in output, output
        assert sorted(_dispositions(project).values()) == ["success"] * 8, output
        assert _batches(project) == batches, output

    def test_a_dry_run_writes_nothing(self, tmp_path):
        project = _collected_with_the_fault(tmp_path)

        code, output = _agac(project, "retry", "-a", WORKFLOW, "--dry-run")

        assert code == 0, output
        assert set(_dispositions(project).values()) == {"deferred"}, output


class TestARecordTheProviderLeftOut:
    def test_the_next_run_reads_it_failed(self, tmp_path):
        project = _collected_with_the_fault(tmp_path, leave_one_out=True)
        failed = _failed_record(project)
        batches = _batches(project)

        code, output = _agac(project, "run", "-a", WORKFLOW)

        assert code == 0, output
        held = _dispositions(project)
        assert held.pop(failed) == "failed", output
        assert sorted(held.values()) == ["success"] * 7, output
        assert _batches(project) == batches, output
        assert _status(project)["status"] == "completed_with_failures", output

    @pytest.mark.parametrize(
        "first", [(), ("run", "-a", WORKFLOW)], ids=["retry", "run-then-retry"]
    )
    def test_a_retry_repairs_it_and_only_it(self, tmp_path, first):
        project = _collected_with_the_fault(tmp_path, leave_one_out=True)
        _failed_record(project)
        batches = _batches(project)
        if first:
            code, output = _agac(project, *first)
            assert code == 0, output

        code, output = _agac(project, "retry", "-a", WORKFLOW)
        assert code == 0, output
        assert "Records to retry: 1" in output, output
        (repair,) = set(_batches(project)) - set(batches)
        assert len(json.loads(repair.read_text())["tasks"]) == 1, output
        code, collected = _agac(project, "run", "-a", WORKFLOW)
        assert code == 0, collected

        assert sorted(_dispositions(project).values()) == ["success"] * 8, output + collected
        assert [row["_state"] for row in _all_rows(project)] == ["processed"] * 8

    def test_a_dry_run_counts_it(self, tmp_path):
        project = _collected_with_the_fault(tmp_path, leave_one_out=True)

        code, output = _agac(project, "retry", "-a", WORKFLOW, "--dry-run")

        assert code == 0, output
        assert "Records to retry: 1" in output, output
        assert set(_dispositions(project).values()) == {"deferred"}, output
