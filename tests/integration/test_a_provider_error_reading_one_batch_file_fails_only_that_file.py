"""A provider error while one batch file is read fails that file's records alone.

The collect pass stopped on any RuntimeError, whoever raised it, so one an SDK raised for
one file left the files after it uncollected and the failed file's records `deferred`. It
is that file's failure: its records are marked failed with the provider's error, the pass
collects the other files, and `agac retry` sends that file's records again.
Only the provider's error is stood in for, raised where the mock provider reads results.
"""

import json
from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from agent_actions.cli.exit_codes import EXIT_PAUSED, EXIT_RECORD_FAILURES
from agent_actions.cli.main import cli
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_FAILED
from tests.integration.test_a_stopped_action_keeps_only_what_its_config_still_answers import (
    ACTION,
    EVERY_PAGE,
    MODEL,
    PAGES,
    WORKFLOW,
    _backend,
    _run,
    _sent,
    _sent_since,
    _status,
    _stored,
    project,  # noqa: F401
)

SDK_ERROR = "Cannot send a request, as the client has been closed."


@contextmanager
def _first_file_unreadable():
    """The provider raises a bare RuntimeError reading the batch of pages1.json."""
    read = AgacBatchClient._fetch_raw_results

    def failing(self, batch_id):
        self._state_for(batch_id)
        tasks = json.dumps(self._tasks_by_batch.get(batch_id, []))
        if any(page in tasks for page in PAGES["pages1.json"]):
            raise RuntimeError(SDK_ERROR)
        return read(self, batch_id)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(AgacBatchClient, "_fetch_raw_results", failing)
        yield


def _record_ids(root, disposition):
    backend = _backend(root)
    try:
        return {
            row["record_id"]: row.get("reason") or ""
            for row in backend.get_disposition(ACTION, disposition=disposition, snapshots=False)
        }
    finally:
        backend.close()


def _pages_of(root, guids):
    backend = _backend(root)
    try:
        pages = {}
        for path in backend.list_target_files(ACTION):
            for row in backend._read_target_raw(ACTION, path):
                pages[row["source_guid"]] = row["content"]["source"]["page_content"]
        return sorted(pages[guid] for guid in guids)
    finally:
        backend.close()


def test_the_pass_collects_the_other_file_and_fails_the_records_of_this_one(
    project,  # noqa: F811
):
    assert _run("--fresh").exit_code == EXIT_PAUSED

    with _first_file_unreadable():
        result = _run()

    assert result.exit_code == EXIT_RECORD_FAILURES, result.output
    assert _status(project) == "completed_with_failures"
    collected = _stored(project)
    assert _pages_of(project, collected) == sorted(PAGES["pages2.json"])
    failed = _record_ids(project, DISPOSITION_FAILED)
    assert len(failed) == len(PAGES["pages1.json"])
    assert all(SDK_ERROR in reason for reason in failed.values()), failed
    assert not set(failed) & set(_record_ids(project, DISPOSITION_DEFERRED))


def test_agac_retry_sends_that_file_again_and_the_action_completes(
    project,  # noqa: F811
):
    assert _run("--fresh").exit_code == EXIT_PAUSED
    with _first_file_unreadable():
        _run()
    sent = _sent(project)

    retried = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])
    assert retried.exit_code == EXIT_PAUSED, retried.output
    result = _run()

    assert result.exit_code == 0, result.output
    assert _sent_since(project, sent) == [(page, MODEL) for page in sorted(PAGES["pages1.json"])]
    assert _status(project) == "completed"
    assert len(_stored(project)) == len(EVERY_PAGE)
    assert _record_ids(project, DISPOSITION_FAILED) == {}
