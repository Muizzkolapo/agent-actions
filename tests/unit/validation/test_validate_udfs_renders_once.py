"""validate-udfs renders the workflow file once, and the inspector parses the text it is given."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import agent_actions.prompt.render_workflow as render_workflow
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.validation.validate_udfs import ValidateUDFsCommand
from tests.integration.test_run_warns_on_a_bare_inline_array import _project

_REAL_RENDER = render_workflow.render_pipeline_with_templates


def _counting(calls: list[str]):
    def spy(config_path, *args, **kwargs):
        calls.append(Path(config_path).name)
        return _REAL_RENDER(config_path, *args, **kwargs)

    return spy


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in [k for k in sys.modules if k.startswith("agent_actions._udfs.")]:
        del sys.modules[name]
    root = _project(tmp_path)
    monkeypatch.chdir(root)
    return root


def test_validate_udfs_renders_the_workflow_file_once(project):
    calls: list[str] = []

    with patch.object(render_workflow, "render_pipeline_with_templates", _counting(calls)):
        result = ValidateUDFsCommand("w", "tools").validate()

    assert result["valid"] is True, result
    assert calls.count("w.yml") == 1
    assert calls.count("agent_actions.yml") >= 1


def test_validate_udfs_reads_the_workflow_file_once(project):
    real_read = render_workflow._load_yaml_content
    reads: list[str] = []

    def spy(yaml_path, *args, **kwargs):
        reads.append(Path(yaml_path).name)
        return real_read(yaml_path, *args, **kwargs)

    with patch.object(render_workflow, "_load_yaml_content", spy):
        result = ValidateUDFsCommand("w", "tools").validate()

    assert result["valid"] is True, result
    assert reads.count("w.yml") == 1
    assert reads.count("agent_actions.yml") >= 1


def test_the_inspector_parses_the_given_workflow_text_and_does_not_render_it(project):
    workflow_file = project / "agent_workflow" / "w" / "agent_config" / "w.yml"
    rendered = _REAL_RENDER(str(workflow_file), str(project / "templates"), project_root=project)
    given = rendered.replace("name: pick", "name: given_pick")
    assert given != rendered
    calls: list[str] = []

    with patch.object(render_workflow, "render_pipeline_with_templates", _counting(calls)):
        configs = WorkflowInspector(
            "w",
            project_root=project,
            user_code_path=str(project / "tools"),
            rendered_workflow=given,
        ).load()

    assert list(configs) == ["given_pick"]
    assert "w.yml" not in calls
    assert calls.count("agent_actions.yml") >= 1


def test_the_inspector_renders_the_workflow_file_when_given_no_text(project):
    calls: list[str] = []

    with patch.object(render_workflow, "render_pipeline_with_templates", _counting(calls)):
        configs = WorkflowInspector(
            "w", project_root=project, user_code_path=str(project / "tools")
        ).load()

    assert list(configs) == ["pick"]
    assert calls.count("w.yml") == 1
