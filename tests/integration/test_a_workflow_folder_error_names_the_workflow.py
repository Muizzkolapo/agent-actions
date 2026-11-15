"""An error finding a workflow's folders names the requested workflow, on every route."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.config import project_paths
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.errors import ValidationError
from agent_actions.logging.errors import format_user_error
from agent_actions.utils.file_handler import FileHandler
from tests._support.agac_cli import run_agac

_WORKFLOW = """\
name: {name}
description: "A workflow"
version: "0.1.0"
actions: []
"""

_INVALID = "Configuration Error: Invalid configuration in agent '{wf}'"

_CASES = {
    "no-folder": ("ql_absent", "'ql_absent/agent_config' does not exist", _INVALID),
    "no-agent-config": ("ql_hollow", "'ql_hollow/agent_config' does not exist", _INVALID),
    "no-agent-io": ("ql_noio", "'ql_noio/agent_io' does not exist", _INVALID),
    "two-folders": (
        "ql_twin",
        "Multiple workflows named 'ql_twin' found",
        "Operation Failed: agent '{wf}'",
    ),
}

_ROUTES = {
    "inspect": ("inspect", "-a", "{wf}"),
    "inspect-action": ("inspect", "action", "-a", "{wf}", "pick"),
    "inspect-context": ("inspect", "context", "-a", "{wf}", "pick"),
    "expect-list": ("expect", "list", "-a", "{wf}"),
    "expect-report": ("expect", "report", "-a", "{wf}"),
    "run": ("run", "-a", "{wf}"),
    "retry": ("retry", "-a", "{wf}"),
    "schema": ("schema", "-a", "{wf}"),
    "dispositions": ("dispositions", "-a", "{wf}"),
    "validate-udfs": ("validate-udfs", "-a", "{wf}", "-u", "tools"),
    "preview": ("preview", "-w", "{wf}"),
    "status": ("status", "-a", "{wf}"),
    "traces": ("traces", "-w", "{wf}", "-a", "pick"),
    "records": ("records", "-w", "{wf}"),
}


def _workflow(folder: Path, name: str) -> None:
    (folder / "agent_config").mkdir(parents=True)
    (folder / "agent_config" / f"{name}.yml").write_text(_WORKFLOW.format(name=name))


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "agent_workflow" / "ql_hollow").mkdir(parents=True)
    _workflow(root / "agent_workflow" / "ql_noio", "ql_noio")
    _workflow(root / "agent_workflow" / "ql_whole", "ql_whole")
    (root / "agent_workflow" / "ql_whole" / "agent_io").mkdir()
    for team in ("team_a", "team_b"):
        _workflow(root / "agent_workflow" / team / "ql_twin", "ql_twin")
        (root / "agent_workflow" / team / "ql_twin" / "agent_io").mkdir()
    (root / "tools").mkdir()
    (root / "agent_actions.yml").write_text("default_agent_config:\n  model_name: mock\n")
    return root


@pytest.mark.parametrize("route", sorted(_ROUTES))
@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_workflow_folder_error_names_the_workflow(tmp_path, case, route):
    workflow, problem, title = _CASES[case]
    args = [arg.format(wf=workflow) for arg in _ROUTES[route]]
    result = run_agac(_project(tmp_path), *args)
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode == 1, output
    assert problem in output, output
    assert f"Error: {title.format(wf=workflow)} Problem: " in output, output
    assert f"Agent: {workflow} " in output, output
    assert "'unknown'" not in output, output


def _fail(*_args, **_kwargs):
    raise OSError("disk unreadable")


@pytest.mark.parametrize(
    ("target", "attribute", "problem"),
    [
        (FileHandler, "get_agent_paths", "Failed to get agent paths"),
        (project_paths, "resolve_absolute_path", "Failed to create project paths"),
    ],
)
def test_an_unexpected_path_failure_names_the_workflow(
    tmp_path, monkeypatch, target, attribute, problem
):
    monkeypatch.setattr(target, attribute, _fail)
    root = _project(tmp_path)

    with pytest.raises(ValidationError) as excinfo:
        ProjectPathsFactory.create_project_paths("ql_whole", "ql_whole.yml", project_root=root)
    output = format_user_error(excinfo.value)

    assert excinfo.value.args == (problem,)
    assert "Problem: disk unreadable" in output, output
    assert "Invalid configuration in agent 'ql_whole'" in output, output
    assert "'unknown'" not in output, output
