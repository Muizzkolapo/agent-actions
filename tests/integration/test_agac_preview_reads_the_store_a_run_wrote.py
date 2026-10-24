"""`agac preview` reads the store a real `agac run` wrote, in every documented form (1547).

Each command is a real `agac` process against a project in a tmp dir.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "preview_store"
ACTION = "tag"

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def preview_tag(data: Any, *args) -> list[dict]:
    return [{"tag": "T-" + str(data["source"]["item_id"])}]
"""

CONFIG = f"""name: {WORKFLOW}
description: "a store for agac preview to read"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: {ACTION}
    kind: tool
    intent: "tag each item"
    impl: preview_tag
    schema: tag_out
    context_scope: {{ observe: [source.item_id] }}
"""


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("preview")
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  api_key: OLLAMA_API_KEY\n  model_name: mock\n"
        'tool_path: ["tools"]\nschema_path: schema\n'
    )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG)
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}])
    )
    (root / "tools" / WORKFLOW / "preview_tools.py").write_text(TOOLS)
    (root / "schema" / WORKFLOW / "tag_out.yml").write_text(
        "name: tag_out\nfields:\n  - id: tag\n    type: string\n"
    )
    result = run_agac(root, "run", "-a", WORKFLOW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (workflow / "agent_io" / "store" / f"{WORKFLOW}.db").is_file()
    return root


def _preview(root: Path, *args: str) -> str:
    result = run_agac(root, "preview", "-w", WORKFLOW, *args)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "not initialized" not in output
    return output


def test_preview_lists_the_actions_with_data(project):
    output = _preview(project)

    row = next(line for line in output.splitlines() if f" {ACTION} " in line)
    assert [cell.strip() for cell in row.strip("│ ").split("│")] == ["1", ACTION, "3", "1"]


def test_preview_of_an_action_shows_its_records(project):
    output = _preview(project, "-a", ACTION)

    assert "Total Records: 3" in output
    assert all(f"T-{item}" in output for item in "abc")


def test_preview_as_json_prints_the_action_fields(project):
    result = run_agac(project, "preview", "-w", WORKFLOW, "-a", ACTION, "-f", "raw")
    assert result.returncode == 0, result.stdout + result.stderr
    records = json.loads(result.stdout.splitlines()[-1])

    assert sorted(record["content"]["tag"] for record in records) == ["T-a", "T-b", "T-c"]
    assert "T-a" in _preview(project, "-a", ACTION, "-f", "json")


def test_preview_stats_counts_the_stored_records(project):
    output = _preview(project, "--stats")

    assert "Source Records: 3" in output
    assert "Target Records: 3" in output


def test_preview_of_an_action_with_no_data_says_so(project):
    """Control: the same command over a name the store does not hold."""
    output = _preview(project, "-a", "nothing_here")

    assert "No data found for action 'nothing_here'" in output
    assert "T-a" not in output
