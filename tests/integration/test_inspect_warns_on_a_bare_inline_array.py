"""`agac inspect` warns for each inline schema field typed bare `array`, and still passes."""

from __future__ import annotations

import json
from pathlib import Path

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
description: "Inline arrays with and without an item type"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: pick
    kind: tool
    intent: "Pick candidates"
    impl: bare_array_pick
    schema:
      candidates: array
      picks: "array!"
      tags: "array[string]"
      rows: "array[object]"
    context_scope: { observe: [source.page_id] }
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def bare_array_pick(data: dict[str, Any]) -> dict[str, Any]:
    return {"candidates": [], "picks": [], "tags": [], "rows": []}
"""


def _message(field: str) -> str:
    return (
        f"Action 'pick': inline schema field '{field}' is a bare 'array', so it is read "
        "as an array of strings and an item of any other type fails. Write 'array[string]' "
        "for strings or 'array[object]' for objects."
    )


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(_WORKFLOW)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "alpha"}])
    )
    (root / "prompt_store").mkdir()
    (root / "schema" / "w").mkdir(parents=True)
    (root / "tools" / "w").mkdir(parents=True)
    (root / "tools" / "w" / "bare_array_pick.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def test_inspect_prints_one_warning_per_bare_array_field_and_passes(tmp_path):
    project = _project(tmp_path)

    result = run_agac(project, "inspect", "-a", "w")
    output = result.stdout + result.stderr
    flat = " ".join(output.split())

    assert result.returncode == 0, output
    assert _message("candidates") in flat, output
    assert _message("picks") in flat, output
    assert _message("tags") not in flat, output
    assert _message("rows") not in flat, output
