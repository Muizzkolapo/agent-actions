"""A provider error while one batch file is read fails that file's records alone.

The collect pass stopped on any RuntimeError, whoever raised it, so one an SDK raised for
one file left the files after it uncollected and the failed file's records `deferred`. It
is that file's failure: its records are marked failed with the provider's error, the pass
collects the other files, and `agac retry` sends that file's records again. When the
file's records cannot be marked failed either, the action fails and a later run collects
the file. Only the faults are stood in for: the provider's error, raised where the mock
provider reads results, and a store that then cannot read what the file was sent.
"""

import json
import sqlite3
from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from agent_actions.cli.exit_codes import EXIT_PAUSED, EXIT_RECORD_FAILURES
from agent_actions.cli.main import cli
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_FAILED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
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
def _first_file_unreadable(then_its_map_too: bool = False):
    """The provider raises a bare RuntimeError reading the batch of pages1.json.

    With *then_its_map_too*, the store then cannot read what that file was sent, so its
    records cannot be marked failed either.
    """
    read = AgacBatchClient._fetch_raw_results
    load = SQLiteBackend.load_metadata
    map_key = BatchContextManager._metadata_key(ACTION, "pages1.json")
    provider_failed = False

    def failing(self, batch_id):
        nonlocal provider_failed
        self._state_for(batch_id)
        tasks = json.dumps(self._tasks_by_batch.get(batch_id, []))
        if any(page in tasks for page in PAGES["pages1.json"]):
            provider_failed = True
            raise RuntimeError(SDK_ERROR)
        return read(self, batch_id)

    def locked_after_the_provider_failed(self, key):
        if then_its_map_too and provider_failed and key.startswith(map_key):
            raise sqlite3.OperationalError("database is locked")
        return load(self, key)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(AgacBatchClient, "_fetch_raw_results", failing)
        patched.setattr(SQLiteBackend, "load_metadata", locked_after_the_provider_failed)
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


def _uncollected(root):
    backend = _backend(root)
    try:
        jobs = BatchRegistryManager(backend, ACTION).get_all_jobs()
        return sorted(name for name, entry in jobs.items() if entry.collected_at is None)
    finally:
        backend.close()


def test_a_file_whose_records_cannot_be_marked_is_collected_by_a_later_run(
    project,  # noqa: F811
):
    """Its records stay deferred and the action fails. Stamped collected, or dropped from
    the registry with the failure, the file would be owed by no later run."""
    assert _run("--fresh").exit_code == EXIT_PAUSED

    with _first_file_unreadable(then_its_map_too=True):
        failed = _run()

    assert failed.exit_code == 1, failed.output
    assert "could not be marked failed" in " ".join(failed.output.split()), failed.output
    assert _status(project) == "failed"
    assert _uncollected(project) == ["pages1.json"]
    deferred = set(_record_ids(project, DISPOSITION_DEFERRED)) - {NODE_LEVEL_RECORD_ID}
    assert len(deferred) == len(PAGES["pages1.json"])

    sent = _sent(project)
    for _ in range(4):
        ran = _run()
        assert ran.exit_code in (0, EXIT_PAUSED), ran.output
        if ran.exit_code == 0:
            break

    assert ran.exit_code == 0, ran.output
    assert _status(project) == "completed"
    assert len(_stored(project)) == len(EVERY_PAGE)
    assert _record_ids(project, DISPOSITION_DEFERRED) == {}
    assert _record_ids(project, DISPOSITION_FAILED) == {}
    assert _uncollected(project) == []
    # The other file was collected in the failed run, and is not asked again.
    assert set(_sent_since(project, sent)) <= {(page, MODEL) for page in PAGES["pages1.json"]}
