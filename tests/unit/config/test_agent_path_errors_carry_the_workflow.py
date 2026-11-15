"""Each workflow path error carries the requested workflow name as `agent`."""

from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.errors import AgentActionsError


def _root(tmp_path: Path) -> Path:
    (tmp_path / "agent_actions.yml").write_text("tool_path: [tools]\n")
    return tmp_path


def _raised(root: Path, name: str) -> AgentActionsError:
    with pytest.raises(AgentActionsError) as excinfo:
        ProjectPathsFactory.get_agent_paths(name, project_root=root)
    return excinfo.value


def test_a_missing_agent_config_folder_names_the_workflow(tmp_path):
    root = _root(tmp_path)
    (root / "agent_workflow" / "w").mkdir(parents=True)

    assert _raised(root, "w").context["agent"] == "w"


def test_a_missing_agent_io_folder_names_the_workflow(tmp_path):
    root = _root(tmp_path)
    (root / "agent_workflow" / "w" / "agent_config").mkdir(parents=True)

    assert _raised(root, "w").context["agent"] == "w"


def test_a_name_two_folders_hold_names_the_workflow(tmp_path):
    root = _root(tmp_path)
    for parent in ("a", "b"):
        (root / parent / "w" / "agent_config").mkdir(parents=True)
        (root / parent / "w" / "agent_io").mkdir(parents=True)

    assert _raised(root, "w").context["agent"] == "w"


def test_a_workflow_with_both_folders_raises_nothing(tmp_path):
    root = _root(tmp_path)
    (root / "agent_workflow" / "w" / "agent_config").mkdir(parents=True)
    (root / "agent_workflow" / "w" / "agent_io").mkdir(parents=True)

    config_dir, io_dir = ProjectPathsFactory.get_agent_paths("w", project_root=root)

    assert config_dir.name == "agent_config"
    assert io_dir.name == "agent_io"
