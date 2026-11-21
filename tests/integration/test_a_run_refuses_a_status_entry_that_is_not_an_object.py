"""A run refuses a status file whose action entry is not an object, as `agac status` does.

Every entry in the status file is an action's details. A hand-edited file holding a bare
string for one action crashed the run deep inside the engine with an `AttributeError`.
"""

import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    WORKFLOW,
    project,  # noqa: F401
)


def _status_file(root):
    return root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"


@pytest.mark.parametrize(
    "entry", ["completed", None, ["completed"]], ids=["a string", "null", "a list"]
)
def test_a_run_stops_on_an_action_entry_that_is_not_an_object(project, entry):  # noqa: F811
    status_file = _status_file(project)
    status_file.write_text(json.dumps({ACTION: entry}))

    result = CliRunner().invoke(cli, ["run", "-w", WORKFLOW])

    assert result.exit_code == 1, result.output
    assert not isinstance(result.exception, AttributeError), result.exception
    assert "Status file is corrupted:" in result.output
    assert f"Action '{ACTION}' is not an object: {entry!r}" in result.output
    assert json.loads(status_file.read_text()) == {ACTION: entry}


def test_a_fresh_run_still_starts_over_from_such_a_file(project):  # noqa: F811
    status_file = _status_file(project)
    status_file.write_text(json.dumps({ACTION: "completed"}))

    result = CliRunner().invoke(cli, ["run", "-w", WORKFLOW, "--fresh"])

    assert result.exit_code == 0, result.output
    assert json.loads(status_file.read_text())[ACTION]["status"] == "completed"
