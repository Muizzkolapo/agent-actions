"""An error's own context wins over the command's CLI options; an option fills only a gap."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_preflight_refusal_names_the_workflow import _output, _project

_CONFIG = "agent_workflow/w/agent_config/w.yml"

_SECOND_ACTION = """\
  - name: second
    kind: tool
    intent: "Second"
    impl: no_such_tool_fn
    schema: { rows: string }
    dependencies: [pick]
    context_scope: { observe: [pick.rows] }
"""


def _render_error_project(tmp_path: Path) -> Path:
    root = _project(tmp_path, None)
    config = root / _CONFIG
    config.write_text(
        config.read_text().replace('description: "w"', 'description: "{{ no_such_var.attr }}"')
    )
    return root


def _defects(tmp_path: Path, defect: str) -> tuple[Path, str]:
    if defect == "render":
        return _render_error_project(tmp_path), "'no_such_var' is undefined"
    return _project(tmp_path, "missing-schema"), "names schema 'no_such_schema'"


@pytest.mark.parametrize("defect", ["render", "preflight"])
@pytest.mark.parametrize(
    "route",
    [
        ("run", "-a", _CONFIG),
        ("inspect", "action", "-a", _CONFIG, "pick"),
        ("inspect", "context", "-a", _CONFIG, "pick"),
        ("schema", "-a", _CONFIG),
        ("dispositions", "-a", _CONFIG),
        ("retry", "-a", _CONFIG),
    ],
    ids=lambda route: "-".join(route[: route.index("-a")]),
)
def test_an_error_names_its_workflow_not_the_config_path_given(tmp_path, route, defect):
    root, problem = _defects(tmp_path, defect)

    result = run_agac(root, *route)
    output = _output(result)

    assert result.returncode == 1, output
    assert problem in output, output
    assert "Invalid configuration in agent 'w' " in output, output
    assert "Agent: w " in output, output
    assert f"agent '{_CONFIG}'" not in output, output
    assert f"Agent: {_CONFIG}" not in output, output


@pytest.mark.parametrize(
    "route",
    [("run", "-a", "nope"), ("inspect", "action", "-a", "nope", "pick")],
    ids=["run", "inspect-action"],
)
def test_an_error_without_a_workflow_name_takes_it_from_the_cli_option(tmp_path, route):
    result = run_agac(_project(tmp_path, None), *route)
    output = _output(result)

    assert result.returncode == 1, output
    assert "Agent 'nope' not found" in output, output
    assert "Invalid configuration in agent 'nope' " in output, output
    assert "Agent: nope " in output, output


def test_an_unset_field_option_is_not_shown(tmp_path):
    result = run_agac(_project(tmp_path, None), "records", "-w", "nope")
    output = _output(result)

    assert result.returncode == 1, output
    assert "Agent 'nope' not found" in output, output
    assert "Field:" not in output, output


def test_a_set_field_option_is_shown_when_the_error_names_no_field(tmp_path):
    result = run_agac(_project(tmp_path, None), "records", "-w", "nope", "--field", "rows")
    output = _output(result)

    assert result.returncode == 1, output
    assert "Agent 'nope' not found" in output, output
    assert "Field: rows " in output, output


def test_a_missing_tool_names_the_action_that_names_it_not_the_action_inspected(tmp_path):
    root = _project(tmp_path, None)
    config = root / _CONFIG
    config.write_text(config.read_text() + _SECOND_ACTION)

    result = run_agac(root, "inspect", "action", "-a", "w", "pick")
    output = _output(result)

    assert result.returncode == 1, output
    assert "Function 'no_such_tool_fn' not found" in output, output
    assert "Action: second " in output, output
    assert "Action: pick " not in output, output
