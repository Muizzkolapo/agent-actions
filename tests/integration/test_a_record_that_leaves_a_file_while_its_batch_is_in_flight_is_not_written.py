"""A record that leaves a file while its batch is still in flight is not written into it.

The run that resumes the action after the run checking on the batch was interrupted
records the file's input again, so the collect leaves the departed record out.
"""

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.integration.test_a_batch_the_provider_refuses import (
    CLI_ACTION,
    REPO,
    WORKFLOW,
    _agac,
    _batch_ids,
    _project,
    _stored_rows,
)

# `agac`, stopped by an interrupt while it asks the provider how a batch is doing.
_AGAC_STOPPED_CHECKING = """
import sys
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

def interrupted(self, batch_id):
    raise KeyboardInterrupt()

AgacBatchClient._fetch_status = interrupted
from agent_actions.cli.main import main
sys.argv[0] = "agac"
sys.exit(main())
"""


def _agac_stopped_checking(project):
    subprocess.run(
        [sys.executable, "-c", _AGAC_STOPPED_CHECKING, "run", "-a", WORKFLOW, "-u", "tools"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "PYTHONPATH": str(REPO)},
    )
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[CLI_ACTION]["status"]


def _staging(project, name):
    return project / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / name


def _held_out(project, batch_id, held):
    """Keep the batch in flight at the provider, or let it finish."""
    record = project / ".agac" / "batch_state" / f"{batch_id}.json"
    state = json.loads(record.read_text())
    state.update(
        status="in_progress",
        complete_after_seconds=10**9 if held else 0,
        polls_until_complete=10**9 if held else 0,
    )
    record.write_text(json.dumps(state))


def _collect(project):
    collected = [_agac(project)]
    while collected[-1].status == "batch_submitted" and len(collected) < 4:
        collected.append(_agac(project))
    return collected


@pytest.fixture(scope="module")
def in_flight(tmp_path_factory):
    """a2 leaves a_pages.json while its batch is still at the provider, and the run that
    checks on it is interrupted, so the next run resumes the action with the batch out."""
    project = _project(tmp_path_factory.mktemp("in_flight") / "project", ("a",))
    assert _agac(project, "--fresh").status == "batch_submitted"
    batch = _batch_ids(project)["a_pages.json"]
    _held_out(project, batch, held=True)
    pages = json.loads(_staging(project, "a_pages.json").read_text())
    _staging(project, "a_pages.json").write_text(json.dumps(pages[:1]))
    assert _agac_stopped_checking(project) == "interrupted"
    resumed = _agac(project)
    _held_out(project, batch, held=False)
    return SimpleNamespace(project=project, resumed=resumed, collected=_collect(project))


def test_a_record_that_left_while_its_batch_was_in_flight_is_not_written(in_flight):
    assert in_flight.collected[-1].code == 0, in_flight.collected[-1].output
    assert _stored_rows(in_flight.project)["a_pages.json"] == [("a1", "processed")]
