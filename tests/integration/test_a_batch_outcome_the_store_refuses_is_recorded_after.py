"""A batch record's outcome reads the same however the store refused it (1534).

Two outcomes a collect pass could lose to a store that refused its writes:

- A record the guard filtered is sent nothing, so it was never stamped ``deferred``, and
  its FILTERED was written only by the collect pass. Refused there, the record held no
  disposition for good. It is now recorded FILTERED when the batch is submitted.
- A record that exhausted its retries is settled from its stored row by the next run
  (1524). It was settled as ``retry_exhausted`` with no detail, where collection writes
  ``exhausted_after_{N}_attempts`` with the error, read from the row's retry metadata.

Each run is its own ``agac`` process against the agac provider mock. Only the faults are
stood in for: the store refusing `finalize`'s dispositions, and the provider leaving one
record out of every batch it answers.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests._support.agac_cli import run_agac
from tests.integration.test_a_retry_answers_what_a_split_writes_below_it import (
    WORKFLOW,
    _project,
)

FAULT = "refuse_finalize.txt"
DROPPED = "dropped_custom_id.txt"

STAND_IN = f"""
import sqlite3
from pathlib import Path

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

_many = SQLiteBackend.set_dispositions_batch
_one = SQLiteBackend.set_disposition
_retrieve = AgacBatchClient.retrieve_results


def _refused(action_name):
    return Path({FAULT!r}).exists() and action_name == "finalize"


def refusing_many(self, rows):
    rows = list(rows)
    if any(_refused(row[0]) for row in rows):
        raise sqlite3.OperationalError("database or disk is full")
    return _many(self, rows)


def refusing_one(self, action_name, record_id, disposition, *args, **kwargs):
    if _refused(action_name) and disposition != "deferred":
        raise sqlite3.OperationalError("database or disk is full")
    return _one(self, action_name, record_id, disposition, *args, **kwargs)


def dropping(self, batch_id, output_directory=None):
    results = _retrieve(self, batch_id, output_directory)
    flag = Path({DROPPED!r})
    if not flag.exists():
        return results
    if not flag.read_text() and results:
        flag.write_text(min(result.custom_id for result in results))
    return [result for result in results if result.custom_id != flag.read_text()]


SQLiteBackend.set_dispositions_batch = refusing_many
SQLiteBackend.set_disposition = refusing_one
AgacBatchClient.retrieve_results = dropping
"""

GUARD = "    guard: { condition: 'roll_up.summary != \"Page beta. #1\"', on_false: filter }\n"
RETRIES = "    retry: { enabled: true, max_attempts: 2 }\n"


def _batch_project(tmp_path: Path, extra: str) -> Path:
    project = _project(tmp_path, "batch")
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text() + extra)
    site = project.parent / "refusing_store_site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(STAND_IN)
    return project


def _agac(project: Path, *args: str) -> tuple[int, str]:
    result = run_agac(
        project,
        *args,
        env={
            "PYTHONPATH": str(project.parent / "refusing_store_site"),
            "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0",
        },
    )
    return result.returncode, result.stdout + result.stderr


def _status(project: Path) -> str:
    path = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())["finalize"]["status"]


def _dispositions(project: Path) -> list[tuple[str, str | None, str | None]]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return sorted(
            con.execute(
                "select disposition, reason, detail from record_disposition "
                "where action_name = 'finalize' and record_id != '__node__'"
            ).fetchall(),
            key=str,
        )
    finally:
        con.close()


def _collect_everything(project: Path) -> str:
    """Run until no batch of `finalize` is left to collect."""
    code, output = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    for _ in range(5):
        assert code == 0, output
        if _status(project) != "batch_submitted":
            break
        code, output = _agac(project, "run", "-a", WORKFLOW)
    assert _status(project) != "batch_submitted", output
    return output


class TestARecordTheGuardFiltered:
    def test_it_reads_filtered_though_the_collect_pass_could_not_write(self, tmp_path):
        project = _batch_project(tmp_path, GUARD)
        code, output = _agac(project, "run", "-a", WORKFLOW, "--fresh")
        assert code == 0 and _status(project) == "batch_submitted", output

        (project / FAULT).write_text("")
        code, output = _agac(project, "run", "-a", WORKFLOW)
        (project / FAULT).unlink()
        assert code == 0, output

        code, output = _agac(project, "run", "-a", WORKFLOW)
        assert code == 0, output
        held = [row[0] for row in _dispositions(project)]
        assert sorted(held) == ["filtered"] + ["success"] * 7, output


class TestARecordThatExhaustedItsRetries:
    def test_settled_it_reads_as_collection_would_have_written_it(self, tmp_path):
        reference = _batch_project(tmp_path / "reference", RETRIES)
        (reference / DROPPED).write_text("")
        _collect_everything(reference)
        written = _dispositions(reference)
        (exhausted,) = [row for row in written if row[0] == "exhausted"]
        assert exhausted[1] == "exhausted_after_2_attempts", written
        assert exhausted[2], written

        project = _batch_project(tmp_path / "refused", RETRIES)
        (project / DROPPED).write_text("")
        (project / FAULT).write_text("")
        _collect_everything(project)
        (project / FAULT).unlink()
        assert {row[0] for row in _dispositions(project)} == {"deferred"}

        code, output = _agac(project, "run", "-a", WORKFLOW)

        assert code == 0, output
        assert _dispositions(project) == written, output
        assert _status(project) == "completed_with_failures", output
