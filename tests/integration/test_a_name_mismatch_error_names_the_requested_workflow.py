"""A workflow file whose `name:` differs from its file name is refused under the requested name."""

from __future__ import annotations

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_render_error_names_the_workflow import _project


@pytest.mark.parametrize(
    "route", [("inspect", "-a", "w"), ("expect", "list", "-a", "w")], ids=["inspect", "expect-list"]
)
def test_a_name_mismatch_is_refused_under_the_requested_workflow(tmp_path, route):
    root = _project(tmp_path, "schema")
    config = root / "agent_workflow" / "w" / "agent_config" / "w.yml"
    text = config.read_text().replace("rows: \"array[object:['q', 'n']]\"", 'rows: "string"')
    config.write_text(text.replace("name: w\n", "name: other\n", 1))

    result = run_agac(root, *route)
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode == 1, output
    assert "Invalid configuration in agent 'w'" in output, output
    assert "Agent: w " in output, output
    assert "'None'" not in output, output
    assert "Agent: None" not in output, output
