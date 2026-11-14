"""A preflight refusal names the workflow when `-a` is given as the path to its config file."""

from __future__ import annotations

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_preflight_refusal_names_the_workflow import (
    _REFUSALS,
    _output,
    _project,
)

_CONFIG = "agent_workflow/w/agent_config/w.yml"


@pytest.mark.parametrize(
    "route",
    [("inspect", "-a", _CONFIG), ("expect", "list", "-a", _CONFIG)],
    ids=["inspect", "expect-list"],
)
def test_a_refusal_names_the_workflow_not_the_path_given(tmp_path, route):
    result = run_agac(_project(tmp_path, "missing-schema"), *route)
    output = _output(result)

    assert result.returncode == 1, output
    assert _REFUSALS["missing-schema"][1] in output, output
    assert "agent 'w'" in output, output
    assert "Agent: w " in output, output
    assert _CONFIG not in output.split("Problem:")[0], output
