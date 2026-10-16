"""A file whose input is now empty keeps nothing of the batch it was last sent in.

If the provider ends every batch of an action, the next run sends the files again. A file
whose input has since gone empty is stored empty instead, and its failed or cancelled entry,
context map and recorded inputs stayed behind: the action then read as owed a batch it would
never collect, and every later run paused on it.
"""

import json
from types import SimpleNamespace

import pytest

from tests.integration.test_a_batch_the_provider_ends_without_results import (
    _agac,
    _the_provider_ends,
)
from tests.integration.test_a_batch_the_provider_refuses import (
    CLI_ACTION,
    WORKFLOW,
    _batch_ids,
    _project,
    _registry,
    _store,
    _stored_rows,
)


def _metadata_keys(project) -> list[str]:
    con = _store(project)
    try:
        return sorted(
            key
            for (key,) in con.execute("select key from workflow_metadata")
            if key.endswith(":b_pages.json") and CLI_ACTION in key
        )
    finally:
        con.close()


@pytest.fixture(scope="module", params=["failed", "cancelled"])
def runs(request, tmp_path_factory):
    """Both files sent and ended by the provider, then b_pages.json is emptied."""
    project = _project(tmp_path_factory.mktemp(request.param) / "project")
    assert _agac(project, "--fresh").status == "batch_submitted"
    for batch_id in _batch_ids(project).values():
        _the_provider_ends(project, batch_id, request.param)
    ended = _agac(project)

    staging = project / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    (staging / "b_pages.json").write_text(json.dumps([]))
    resent = _agac(project)
    collected = [_agac(project)]
    while collected[-1].status == "batch_submitted" and len(collected) < 3:
        collected.append(_agac(project))
    return SimpleNamespace(project=project, ended=ended, resent=resent, collected=collected)


def test_the_action_completes_on_the_run_that_collects_the_other_file(runs):
    assert runs.collected[-1].code == 0, runs.collected[-1].output
    assert runs.collected[-1].status == "completed", runs.collected[-1].output


def test_the_emptied_file_is_stored_empty_and_the_other_is_answered(runs):
    stored = _stored_rows(runs.project)

    assert stored.get("b_pages.json", []) == []
    assert sorted(page for page, _ in stored["a_pages.json"]) == ["a1", "a2"]


def test_no_entry_for_the_emptied_file_is_left_in_the_registry(runs):
    assert "b_pages.json" not in _registry(runs.project)


def test_nothing_else_is_kept_of_its_batch(runs):
    assert _metadata_keys(runs.project) == []
