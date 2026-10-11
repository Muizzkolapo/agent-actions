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
    _cycle,
    _deferred_ids,
    _dispositions,
    _project,
    _set_disposition,
    _unwrapped,
    submitted_and_collected,  # noqa: F401
)

READER = """  - name: tagger
    kind: tool
    run_mode: online
    dependencies: [summarize]
    intent: "Tag"
    schema: batch_field_rules_output
    impl: tag_density
    context_scope: { observe: [summarize.summary] }
    expect: { repair: none }
"""

TAG_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def tag_density(data: Any, *args) -> list[dict]:
    return [{"summary": str((data or {}).get("summary", "")), "exam_density": "high"}]
"""


@pytest.fixture
def finished_not_collected(tmp_path):
    return _submit_and_finish(_project(tmp_path))


@pytest.fixture
def finished_not_collected_with_a_reader(tmp_path):
    """The same batch, read by an online tool the run has not reached: it stops at the
    submission, and the next run collects before it goes on."""
    root = _project(tmp_path)
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + READER)
    (root / "tools" / WORKFLOW).mkdir(parents=True, exist_ok=True)
    (root / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)
    return _submit_and_finish(root)


def _submit_and_finish(root):
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


@pytest.mark.parametrize("left_as", ["checking_batch", "failed"])
def test_abandoning_gets_past_an_action_left_collecting_or_failed(finished_not_collected, left_as):
    """The provider has forgotten the batch, so no run can collect it: abandoning is the
    only way on, and the batch's records are what the action has left to answer."""
    project = finished_not_collected
    named = _deferred_ids(project)[0]
    _set_disposition(project, named, "failed")
    _set_action_status(project, left_as)

    code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", named, "--abandon-in-flight")

    assert code == 0, output
    assert "Abandoning" in _unwrapped(output), output


def _statuses(project):
    (status_file,) = (project / "agent_workflow" / WORKFLOW).rglob("*status*.json")
    return {
        name: details["status"] for name, details in json.loads(status_file.read_text()).items()
    }


def _rows_at(project, action):
    backend = _backend(project)
    try:
        return sorted(
            r["source_guid"]
            for path in backend.list_target_files(action)
            for r in backend.read_target(action, path)
            if r.get("source_guid")
        )
    finally:
        backend.close()


def test_a_reader_behind_an_uncollected_batch_is_left_to_the_batch(
    finished_not_collected_with_a_reader,
):
    """The reader is pending only because the run stopped at the batch. Refused for it,
    a retry that must abandon the batch had no way on."""
    project = finished_not_collected_with_a_reader
    assert _statuses(project) == {ACTION: "batch_submitted", "tagger": "pending"}
    named = _deferred_ids(project)[0]
    _set_disposition(project, named, "failed")

    code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", named)
    assert code != 0, output
    assert "finished, not collected" in _unwrapped(output), output

    code, output = _agac(project, "retry", "-a", WORKFLOW, "--record", named, "--abandon-in-flight")
    assert code == 0, output

    # The retry stops at its own submission, and the run that collects it runs the
    # reader whole; the records the abandoned batch held are failures a retry reaches.
    _cycle(project, "run", "-a", WORKFLOW)
    _cycle(project, "retry", "-a", WORKFLOW)
    assert len(_rows_at(project, ACTION)) == RECORDS
    assert _rows_at(project, "tagger") == _rows_at(project, ACTION)
