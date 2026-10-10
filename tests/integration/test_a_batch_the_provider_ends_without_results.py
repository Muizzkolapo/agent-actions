"""A batch the provider ends without results costs its file's records, not the action.

A batch the provider failed or cancelled before it finished returns nothing, and no later
run can read it. Passed over, a failed one paused every run after it, and a cancelled one
let the action complete with that file's records still deferred; `agac retry` found
neither, since no record was failed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_batch_the_provider_refuses import (
    CLI_ACTION,
    WORKFLOW,
    _answered,
    _batch_ids,
    _project,
    _store,
    _stored_rows,
)

_NOW = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}


def _agac(project: Path, *args: str) -> SimpleNamespace:
    result = run_agac(project, "run", "-a", WORKFLOW, "-u", "tools", *args, env=_NOW)
    io_dir = project / "agent_workflow" / WORKFLOW / "agent_io"
    status = json.loads((io_dir / ".agent_status.json").read_text())[CLI_ACTION]["status"]
    return SimpleNamespace(
        code=result.returncode, output=result.stdout + result.stderr, status=status
    )


def _retry(project: Path) -> SimpleNamespace:
    result = run_agac(project, "retry", "-a", WORKFLOW, env=_NOW)
    return SimpleNamespace(code=result.returncode, output=result.stdout + result.stderr)


def _the_provider_ends(project: Path, batch_id: str, status: str) -> None:
    """End the batch in the agac provider's own record of it, never to finish after.

    The agac provider finishes any batch once its delay has passed, whatever its record
    says, so the delay goes too.
    """
    record = project / ".agac" / "batch_state" / f"{batch_id}.json"
    state = json.loads(record.read_text())
    state.update(status=status, complete_after_seconds=10**9, polls_until_complete=0)
    record.write_text(json.dumps(state))


def _dispositions(project: Path) -> list[tuple[str, str]]:
    """Each record's disposition, with the reason it was given."""
    con = _store(project)
    try:
        return sorted(
            con.execute(
                "select disposition, coalesce(reason, '') from record_disposition "
                "where action_name = ? and record_id != '__node__'",
                (CLI_ACTION,),
            ).fetchall()
        )
    finally:
        con.close()


class TestABatchTheProviderEndsBesideOneItFinishes:
    """a_pages.json's batch finishes; the provider ends b_pages.json's before it does."""

    @pytest.fixture(scope="class", params=["failed", "cancelled"])
    def runs(self, request, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp(request.param) / "project")
        submitted = _agac(project, "--fresh")
        assert submitted.status == "batch_submitted", submitted.output
        sent = _batch_ids(project)
        _the_provider_ends(project, sent["b_pages.json"], request.param)

        ended = _agac(project)
        dispositions = _dispositions(project)
        after = _agac(project)
        retried = _retry(project)
        collected = [_agac(project)]
        while collected[-1].status == "batch_submitted" and len(collected) < 3:
            collected.append(_agac(project))
        return SimpleNamespace(
            project=project,
            sent=sent,
            ended=ended,
            dispositions=dispositions,
            after=after,
            retried=retried,
            collected=collected,
        )

    def test_the_run_that_finds_it_completes_the_action_with_failures(self, runs):
        assert runs.ended.code == 0, runs.ended.output
        assert runs.ended.status == "completed_with_failures", runs.ended.output

    def test_the_records_of_its_file_are_marked_failed_naming_the_batch(self, runs):
        assert [disposition for disposition, _ in runs.dispositions] == [
            "failed",
            "failed",
            "success",
            "success",
        ]
        reasons = [reason for disposition, reason in runs.dispositions if disposition == "failed"]
        assert all(runs.sent["b_pages.json"] in reason for reason in reasons), reasons

    def test_the_run_names_the_file_and_its_batch(self, runs):
        assert f"Could not read b_pages.json (batch {runs.sent['b_pages.json']})" in (
            runs.ended.output
        )

    def test_the_run_after_it_does_not_wait_on_it(self, runs):
        assert runs.after.code == 0, runs.after.output
        assert runs.after.status == "completed_with_failures", runs.after.output

    def test_agac_retry_sends_its_records_again_and_every_record_ends_answered(self, runs):
        assert runs.retried.code == 0, runs.retried.output
        assert "Nothing to retry" not in runs.retried.output
        assert runs.collected[-1].status == "completed", runs.collected[-1].output
        assert _stored_rows(runs.project) == _answered("a", "b")
