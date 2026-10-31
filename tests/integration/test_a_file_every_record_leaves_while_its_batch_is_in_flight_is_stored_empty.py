"""A file that held answers, emptied while its next batch is in flight, is stored empty.

The file is sent again by `--rerun` under an edit, every record leaves it while that batch
is still at the provider, and the run checking on the batch is interrupted, so the next run
resumes the action with the batch in flight. The answers the file held before go with it.
"""

import json
from types import SimpleNamespace

import pytest

from tests.integration.test_a_batch_the_provider_refuses import (
    CLI_ACTION,
    _agac,
    _batch_ids,
    _project,
    _registry,
    _stored_rows,
)
from tests.integration.test_a_record_that_leaves_a_file_while_its_batch_is_in_flight_is_not_written import (  # noqa: E501
    _agac_stopped_checking,
    _collect,
    _held_out,
    _staging,
)


def _edit_the_prompt(project):
    prompts = project / "prompt_store" / "p.md"
    text = prompts.read_text()
    edited = text.replace("Summarise the page in one sentence", "Summarise the page in five words")
    assert edited != text
    prompts.write_text(edited)


@pytest.fixture(scope="module")
def emptied(tmp_path_factory):
    project = _project(tmp_path_factory.mktemp("held") / "project", ("a", "b"))
    assert _agac(project, "--fresh").status == "batch_submitted"
    assert _collect(project)[-1].status == "completed"
    held_before = _stored_rows(project)

    _edit_the_prompt(project)
    assert _agac(project, "--rerun", CLI_ACTION).status == "batch_submitted"
    batch = _batch_ids(project)["a_pages.json"]
    _held_out(project, batch, held=True)
    _staging(project, "a_pages.json").write_text(json.dumps([]))
    assert _agac_stopped_checking(project) == "interrupted"
    resumed = _agac(project)
    _held_out(project, batch, held=False)
    return SimpleNamespace(
        project=project, held_before=held_before, resumed=resumed, collected=_collect(project)
    )


def test_the_premise_the_file_held_answers_before(emptied):
    assert sorted(page for page, _ in emptied.held_before["a_pages.json"]) == ["a1", "a2"]


def test_the_emptied_file_is_stored_empty_and_the_other_is_answered(emptied):
    assert emptied.collected[-1].status == "completed", emptied.collected[-1].output
    stored = _stored_rows(emptied.project)

    assert stored["a_pages.json"] == []
    assert sorted(page for page, _ in stored["b_pages.json"]) == ["b1", "b2"]


def test_its_batch_is_collected_rather_than_dropped(emptied):
    assert _registry(emptied.project)["a_pages.json"]["collected_at"] is not None
