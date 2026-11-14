"""A configuration error raised while the workflow config renders names the workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "{description}"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: pick
{action}
    schema:
      rows: "{rows_type}"
    context_scope: {{ observe: [source.page_id] }}
"""

_TOOL_ACTION = """\
    kind: tool
    intent: "Pick rows"
    impl: pick_rows"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def pick_rows(data: dict[str, Any]) -> dict[str, Any]:
    return {"rows": []}
"""

_FAILURES = {
    "schema": {"rows_type": "array[object:['q', 'n']]"},
    "jinja": {"description": "{% if %}"},
    "prompt": {"action": '    intent: "Pick rows"\n    prompt: $w.missing'},
}

_ROUTES = {
    "inspect": ("inspect", "-a", "w"),
    "expect-list": ("expect", "list", "-a", "w"),
    "expect-report": ("expect", "report", "-a", "w"),
    "run": ("run", "-a", "w"),
}


def _project(tmp_path: Path, failure: str) -> Path:
    fields = {"description": "w", "action": _TOOL_ACTION, "rows_type": "string"}
    fields.update(_FAILURES[failure])
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(_WORKFLOW.format(**fields))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "a"}])
    )
    (root / "prompt_store").mkdir()
    (root / "schema" / "w").mkdir(parents=True)
    (root / "tools" / "w").mkdir(parents=True)
    (root / "tools" / "w" / "pick_rows.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


@pytest.mark.parametrize("route", sorted(_ROUTES))
@pytest.mark.parametrize("failure", sorted(_FAILURES))
def test_a_render_time_error_names_the_workflow(tmp_path, failure, route):
    result = run_agac(_project(tmp_path, failure), *_ROUTES[route])
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode == 1, output
    assert "Invalid configuration in agent 'w'" in output, output
    assert "Agent: w " in output, output
    assert "'None'" not in output, output
    assert "Agent: None" not in output, output
