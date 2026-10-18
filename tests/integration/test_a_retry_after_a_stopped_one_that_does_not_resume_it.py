"""A retry that does not resume a stopped one leaves it to be resumed (1524).

A retry stopped after `roll_up` split alpha again, but before the actions below it ran,
is resumed by the next ``agac retry``: it starts where the stopped one did and takes out
what the actions below held for the rows the split replaced (1519). A retry that put back
the stopped one's failures and then did not run deleted its record of that retry with
them: one with ``--from`` below the stopped retry's start said "Nothing to retry" and
exited 0, one naming a record it could not find was refused. Either way the stopped retry
could no longer be resumed: the next ``agac retry`` refused, and the split's rows stayed
unanswered below it with alpha's tombstone.

Now a ``--from`` below the stopped retry's start is refused before anything is put back,
and a retry that puts the failures back keeps its record of the stopped one until it
writes its own, so the next ``agac retry`` resumes it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_retry_resumed_after_a_stop_below_a_split import (
    ALL_FINAL,
    WORKFLOW,
    _agac,
    _project,
    _rows,
    _run,
    _statuses,
    _summaries,
)


def _stopped(tmp_path: Path, finalize: str) -> Path:
    """Fail alpha, then stop the retry that repairs it after the split has re-run."""
    project = _project(tmp_path, finalize)
    (project / "FAIL_AT").write_text("flatten")
    _run(project, "--fresh")
    (project / "FAIL_AT").unlink()
    (project / "STOP").write_text("")
    stopped = _agac(project, "retry", "-a", WORKFLOW, code=130)
    (project / "STOP").unlink()
    assert _statuses(project)["finalize"] == "pending", stopped
    return project


def _try(project: Path, *args: str) -> tuple[int, str]:
    result = run_agac(
        project, "retry", "-a", WORKFLOW, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
    )
    return result.returncode, result.stdout + result.stderr


def _resume(project: Path, finalize: str) -> str:
    output = _agac(project, "retry", "-a", WORKFLOW)
    if finalize == "batch":
        output += _run(project)
    return output


def _answered_below_the_split(project: Path, finalize: str, output: str) -> None:
    rows = _rows(project, "finalize", "pages1.json")
    assert [row.get("_state") for row in rows] == ["processed"] * 4, output
    assert "cannot be attributed" not in output, output
    split = {row["source_guid"] for row in _rows(project, "side", "pages1.json")}
    assert {row["source_guid"] for row in rows} == split, output
    if finalize == "tool":
        assert _summaries(project, "finalize", "pages1.json") == ALL_FINAL


@pytest.mark.parametrize("finalize", ["tool", "batch"])
@pytest.mark.parametrize("below", ["side", "finalize"])
class TestFromBelowTheStoppedRetry:
    def test_it_is_refused_and_names_the_retry_to_resume(self, tmp_path, finalize, below):
        project = _stopped(tmp_path, finalize)

        code, output = _try(project, "--from", below)

        assert code != 0, output
        assert "Nothing to retry" not in output, output
        assert f"agac retry -a {WORKFLOW}" in output and "flatten" in output, output

    def test_the_next_retry_resumes_the_stopped_one(self, tmp_path, finalize, below):
        project = _stopped(tmp_path, finalize)
        _try(project, "--from", below)

        output = _resume(project, finalize)

        _answered_below_the_split(project, finalize, output)

    def test_a_dry_run_reports_the_refusal(self, tmp_path, finalize, below):
        project = _stopped(tmp_path, finalize)

        code, output = _try(project, "--from", below, "--dry-run")

        assert code == 0, output
        assert "would be refused" in output, output


@pytest.mark.parametrize("finalize", ["tool", "batch"])
def test_a_retry_refused_after_putting_back_leaves_the_stopped_one_to_resume(tmp_path, finalize):
    project = _stopped(tmp_path, finalize)
    code, output = _try(project, "--record", "no-such-record")
    assert code != 0 and "not found" in output, output

    output = _resume(project, finalize)

    _answered_below_the_split(project, finalize, output)
