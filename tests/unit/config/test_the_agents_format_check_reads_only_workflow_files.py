"""The `agents:` format check reads workflow files only, and only an agent list."""

import pytest

from agent_actions.config.schema import refuse_agents_format
from agent_actions.errors import ConfigurationError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates


def test_the_project_file_is_not_checked(tmp_path):
    project_file = tmp_path / "agent_actions.yml"
    project_file.write_text("agents: {}\nschema_path: schema\n")
    (tmp_path / "templates").mkdir()

    rendered = render_pipeline_with_templates(
        project_file, tmp_path / "templates", project_root=tmp_path, workflow=False
    )

    assert "agents" in rendered


def test_a_workflow_file_is_checked(tmp_path):
    workflow_file = tmp_path / "w.yml"
    workflow_file.write_text("w:\n  agents:\n    - agent_type: a\n")
    (tmp_path / "templates").mkdir()

    with pytest.raises(ConfigurationError, match="'agents:' format"):
        render_pipeline_with_templates(workflow_file, tmp_path / "templates", project_root=tmp_path)


@pytest.mark.parametrize("value", [1, "x", {"k": "v"}, None])
def test_a_mapping_whose_agents_key_holds_no_list_is_not_the_format(value):
    refuse_agents_format({"name": "w", "defaults": {"agents": value}}, "w.yml")
