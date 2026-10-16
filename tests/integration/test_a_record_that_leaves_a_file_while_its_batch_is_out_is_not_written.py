"""A record that leaves a file while its batch is out is not written into that file.

A run that finds the file's batch out does not send it again, so the collect wrote the
inputs recorded when it was sent. A record removed from staging in between was still
written, where an online run holds only the records the file now has.

The resumed run is the one the batch was collected by after a collect pass stopped partway:
a run that only collects never reads staging again.
"""

import json
from types import SimpleNamespace

import pytest

from tests.integration.test_a_batch_the_provider_refuses import (
    WORKFLOW,
    _agac,
    _project,
    _stored_rows,
)


def _staging(project):
    return project / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "a_pages.json"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """a_pages.json = [a1, a2] is sent; a2 leaves staging, then a collect pass stops."""
    project = _project(tmp_path_factory.mktemp("left") / "project", ("a",))
    submitted = _agac(project, "--fresh")
    assert submitted.status == "batch_submitted", submitted.output
    pages = json.loads(_staging(project).read_text())
    _staging(project).write_text(json.dumps(pages[:1]))
    assert _agac(project, STOP_AT="a_pages.json").code != 0
    collected = [_agac(project)]
    while collected[-1].status == "batch_submitted" and len(collected) < 3:
        collected.append(_agac(project))
    return SimpleNamespace(project=project, collected=collected)


def test_the_batch_is_collected(runs):
    assert runs.collected[-1].code == 0, runs.collected[-1].output
    assert runs.collected[-1].status == "completed", runs.collected[-1].output


def test_the_file_holds_the_record_it_still_has_and_not_the_one_that_left(runs):
    assert _stored_rows(runs.project) == {"a_pages.json": [("a1", "processed")]}
