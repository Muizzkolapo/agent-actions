"""A workflow file in the `agents:` format is refused at load, before anything runs.

agac reads only the actions format: a `name:` and an `actions:` list. The refusal
names the `agents:` format and tells the author to write `actions:`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError
from tests._support.agac_cli import run_agac

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_AGENT = {
    "agent_type": "label_page",
    "model_vendor": "agac-provider",
    "model_name": "mock",
    "prompt": "Label the page.",
}

SHAPES = {
    "agents_key_under_the_name": {"w": {"agents": [_AGENT]}},
    "list_under_the_name": {"w": [_AGENT]},
    "top_level_agents_key": {"name": "w", "description": "Agents", "agents": [_AGENT]},
}


def _project(tmp_path: Path, workflow: dict) -> Path:
    root = tmp_path / "project"
    folder = root / "agent_workflow" / "w"
    (folder / "agent_config").mkdir(parents=True)
    (folder / "agent_config" / "w.yml").write_text(yaml.safe_dump(workflow, sort_keys=False))
    (folder / "agent_io" / "staging").mkdir(parents=True)
    (folder / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "alpha"}])
    )
    (root / "prompt_store").mkdir()
    (root / "templates").mkdir()
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _workflow_file(root: Path) -> Path:
    return root / "agent_workflow" / "w" / "agent_config" / "w.yml"


@pytest.mark.parametrize("shape", SHAPES.values(), ids=SHAPES.keys())
def test_the_config_manager_refuses_it_at_load(tmp_path, shape):
    root = _project(tmp_path, shape)
    manager = ConfigManager(
        str(_workflow_file(root)), str(root / "agent_actions.yml"), project_root=root
    )

    with pytest.raises(ConfigurationError) as refused:
        manager.load_configs()

    message = str(refused.value)
    assert "'agents:' format" in message, message
    assert "'actions:'" in message, message
    assert refused.value.context["file_path"] == "agent_workflow/w/agent_config/w.yml"


@pytest.mark.parametrize("shape", SHAPES.values(), ids=SHAPES.keys())
@pytest.mark.parametrize("command", [("inspect",), ("run", "--fresh")], ids=["inspect", "run"])
def test_the_cli_refuses_it_and_writes_nothing(tmp_path, shape, command):
    root = _project(tmp_path, shape)

    result = run_agac(root, *command, "-a", "w")
    output = result.stdout + result.stderr

    assert result.returncode == 1, output
    assert "'agents:' format" in output, output
    assert "'actions:'" in output, output
    store = root / "agent_workflow" / "w" / "agent_io" / "store"
    assert not list(store.glob("*.db")), output
    assert not (root / "agent_workflow" / "w" / "agent_io" / "target").exists(), output
