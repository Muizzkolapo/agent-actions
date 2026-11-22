"""A workflow file reads an environment variable with `env()`, from the shell or the .env."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

VARIABLE = "AGAC_TEST_WORKFLOW_MODEL"

_PROJECT = """\
default_agent_config:
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "w"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: {{ env('AGAC_TEST_WORKFLOW_RUN_MODE', 'online') }}
  model_vendor: agac-provider
  model_name: {{ env('AGAC_TEST_WORKFLOW_MODEL') }}
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: pick
    intent: "Pick"
    prompt: "Say something about {{ source.page_content }}"
    schema:
      rows: string
    context_scope: { observe: [source.page_content] }
"""


@pytest.fixture(autouse=True)
def _unset(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.delenv("AGAC_TEST_WORKFLOW_RUN_MODE", raising=False)


def _project(tmp_path: Path, dotenv: str = "") -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(_WORKFLOW)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "a"}])
    )
    (root / "prompt_store").mkdir()
    (root / "schema" / "w").mkdir(parents=True)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text(dotenv)
    return root


def _output(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def test_an_unset_variable_without_a_default_refuses_the_load(tmp_path):
    result = run_agac(_project(tmp_path), "inspect", "-a", "w")
    output = _output(result)

    assert result.returncode == 1, output
    assert "Invalid configuration in agent 'w'" in output, output
    assert "agent_config/w.yml': env('AGAC_TEST_WORKFLOW_MODEL') reads" in output, output
    assert "which the environment does not hold, and gives no default" in output, output


def test_the_value_comes_from_the_dotenv(tmp_path):
    root = _project(tmp_path, f"{VARIABLE}=from-dotenv\n")

    result = run_agac(root, "run", "-a", "w")
    output = _output(result)

    assert result.returncode == 0, output
    assert "(agac-provider/from-dotenv)" in output, output


def test_the_shell_outranks_the_dotenv(tmp_path):
    root = _project(tmp_path, f"{VARIABLE}=from-dotenv\n")

    result = run_agac(root, "run", "-a", "w", env={VARIABLE: "from-shell"})
    output = _output(result)

    assert result.returncode == 0, output
    assert "(agac-provider/from-shell)" in output, output
