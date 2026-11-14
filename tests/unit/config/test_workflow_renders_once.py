"""A command that loads a workflow renders the workflow file once and parses that render."""

from pathlib import Path
from unittest.mock import patch

import yaml

import agent_actions.prompt.render_workflow as render_workflow
import agent_actions.prompt.renderer as renderer
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.manager import ConfigManager
from agent_actions.config.project_paths import ProjectPathsFactory
from tests.integration.test_run_warns_on_a_bare_inline_array import _project

_REAL_RENDER = render_workflow.render_pipeline_with_templates


def _counting(calls: list[str]):
    def spy(config_path, *args, **kwargs):
        calls.append(str(config_path))
        return _REAL_RENDER(config_path, *args, **kwargs)

    return spy


def test_the_manager_parses_the_text_it_is_given_and_renders_nothing(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("tool_path: [tools]\n")
    workflow_file = tmp_path / "w.yml"
    workflow_file.write_text("name: on_disk\nactions: []\n")
    given = "name: given\nactions:\n  - name: a\n"
    calls: list[str] = []
    spy = _counting(calls)

    with patch.object(render_workflow, "render_pipeline_with_templates", spy):
        manager = ConfigManager(
            str(workflow_file), "", project_root=tmp_path, rendered_workflow=given
        )
        manager.load_configs()

    assert manager.user_config == yaml.safe_load(given)
    assert calls == []


def test_the_manager_renders_the_file_when_it_is_given_no_text(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("tool_path: [tools]\n")
    workflow_file = tmp_path / "w.yml"
    workflow_file.write_text("name: on_disk\nactions: []\n")
    calls: list[str] = []
    spy = _counting(calls)

    with patch.object(render_workflow, "render_pipeline_with_templates", spy):
        manager = ConfigManager(str(workflow_file), "", project_root=tmp_path)
        manager.load_configs()

    assert manager.user_config["name"] == "on_disk"
    assert calls == [str(workflow_file)]


def test_loading_a_workflow_for_a_command_renders_its_file_once(tmp_path):
    root = _project(tmp_path)
    (root / "templates").mkdir()
    paths = ProjectPathsFactory.create_project_paths("w", "w", auto_create=False, project_root=root)
    workflow_file = root / "agent_workflow" / "w" / "agent_config" / "w.yml"
    calls: list[str] = []
    spy = _counting(calls)

    with (
        patch.object(render_workflow, "render_pipeline_with_templates", spy),
        patch.object(renderer, "render_pipeline_with_templates", spy),
    ):
        workflow = load_workflow("w", paths, root, sends_requests=False, read_only=True)

    assert [Path(c) for c in calls if Path(c).name == "w.yml"] == [workflow_file]
    assert [a["name"] for a in workflow.action_configs.values()] == ["pick"]
