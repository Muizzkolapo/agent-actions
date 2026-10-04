"""Whether a finished batch is still owed is asked of its records.

Not of the registry entry, which has no collected stamp in a store older than the
stamp, and not of the action's status: an action can complete past a file it skipped.
"""

import json

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from tests.integration.test_retry_selection_under_batch import (
    ACTION,
    RECORDS,
    WORKFLOW,
    _agac,
    _backend,
    _deferred_ids,
    _dispositions,
    _project,
    _set_disposition,
    _unwrapped,
    submitted_and_collected,  # noqa: F401
)


@pytest.fixture
def finished_not_collected(tmp_path):
    root = _project(tmp_path)
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(RECORDS)])
    )
    code, output = _agac(root, "run", "-a", WORKFLOW, "--fresh")
    assert code == 0, output
    assert "run again" in output
    backend = _backend(root)
    try:
        registry = BatchRegistryManager(backend, ACTION)
        for entry in registry.get_all_jobs().values():
            registry.update_status(entry.batch_id, BatchStatus.COMPLETED)
    finally:
        backend.close()
    return root


def _set_action_status(project, status):
    (status_file,) = (project / "agent_workflow" / WORKFLOW).rglob("*status*.json")
    statuses = json.loads(status_file.read_text())
    statuses[ACTION]["status"] = status
    status_file.write_text(json.dumps(statuses))


@pytest.mark.parametrize("left_as", ["completed", "checking_batch", "failed"])
def test_a_batch_holding_unanswered_records_is_owed_whatever_the_action_says(
    finished_not_collected, left_as
):
    """Completed too: a collect pass that skips a file it could not check still ends
    the action completed, with that file's batch finished and never collected."""
    project = finished_not_collected
    named = _deferred_ids(project)[0]
    _set_disposition(project, named, "failed")
    _set_action_status(project, left_as)

    code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", named)

    assert code != 0, output
    assert "finished, not collected" in _unwrapped(output), output


def test_a_batch_whose_records_all_failed_is_not_owed(finished_not_collected):
    """Collection threw and every record of the file was marked failed. Nothing waits
    on that batch, and retrying those records is what retry is for."""
    project = finished_not_collected
    for record_id in _deferred_ids(project):
        _set_disposition(project, record_id, "failed")
    _set_action_status(project, "failed")
    named = sorted(_dispositions(project))[0]

    code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", named, "--dry-run")

    assert code == 0, output
    assert "would be refused" not in _unwrapped(output), output


def test_a_dry_run_over_a_finished_batch_says_so_and_changes_nothing(finished_not_collected):
    project = finished_not_collected
    named = _deferred_ids(project)[0]
    _set_disposition(project, named, "failed")
    before = _dispositions(project)

    code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", named, "--dry-run")

    assert code == 0, output
    assert "would be refused" in _unwrapped(output), output
    assert _dispositions(project) == before


def test_a_repair_batch_is_owed_though_its_record_still_has_its_old_row(
    submitted_and_collected,  # noqa: F811
):
    """A retry sent one record again and its batch finished without being collected.
    A run's reset then cleared the record's deferred mark. The record still has the
    row that was judged failed, which says nothing about the batch out for it."""
    project = submitted_and_collected
    first, second = sorted(_dispositions(project))[:2]
    _set_disposition(project, first, "failed")
    code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", first)
    assert code == 0 and "run again" in output, output
    backend = _backend(project)
    try:
        registry = BatchRegistryManager(backend, ACTION)
        for entry in registry.get_all_jobs().values():
            registry.update_status(entry.batch_id, BatchStatus.COMPLETED)
        backend.clear_disposition(ACTION, "deferred")
    finally:
        backend.close()
    _set_disposition(project, second, "failed")

    code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", second)

    assert code != 0, output
    assert "finished, not collected" in _unwrapped(output), output
