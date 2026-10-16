"""A file every record leaves while its batch is out is stored empty once it is collected.

The run that finds the batch out does not send the file again, so the collect wrote the
batch's answers for records the file no longer has. Online stores such a file empty.
"""

import json
from types import SimpleNamespace

import pytest

from tests.integration.test_a_batch_the_provider_refuses import (
    WORKFLOW,
    _agac,
    _project,
    _registry,
    _stored_rows,
)


def _staging(project, name):
    return project / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / name


def _collect(project):
    collected = [_agac(project)]
    while collected[-1].status == "batch_submitted" and len(collected) < 4:
        collected.append(_agac(project))
    return collected


@pytest.fixture(scope="module")
def emptied(tmp_path_factory):
    """Both files sent; a_pages.json is emptied while its batch is out, then a collect stops."""
    project = _project(tmp_path_factory.mktemp("emptied") / "project", ("a", "b"))
    assert _agac(project, "--fresh").status == "batch_submitted"
    _staging(project, "a_pages.json").write_text(json.dumps([]))
    assert _agac(project, STOP_AT="a_pages.json").code != 0
    return SimpleNamespace(project=project, collected=_collect(project))


def test_the_action_completes(emptied):
    assert emptied.collected[-1].code == 0, emptied.collected[-1].output
    assert emptied.collected[-1].status == "completed", emptied.collected[-1].output


def test_the_emptied_file_is_stored_empty_and_the_other_keeps_its_answers(emptied):
    stored = _stored_rows(emptied.project)

    assert stored.get("a_pages.json", []) == []
    assert sorted(page for page, _ in stored["b_pages.json"]) == ["b1", "b2"]


def test_its_batch_is_collected_rather_than_dropped(emptied):
    assert _registry(emptied.project)["a_pages.json"]["collected_at"] is not None
