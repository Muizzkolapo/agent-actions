"""`agac inspect` names an inline `array[object:...]` field whose item fields are not a mapping."""

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
description: "Inline array of objects"
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
    kind: tool
    intent: "Pick rows"
    impl: pick_rows
    schema:
      rows: "{rows_type}"
    context_scope: {{ observe: [source.page_id] }}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def pick_rows(data: dict[str, Any]) -> dict[str, Any]:
    return {"rows": []}
"""


def _inspect(tmp_path: Path, rows_type: str) -> tuple[int, str]:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(_WORKFLOW.format(rows_type=rows_type))
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
    result = run_agac(root, "inspect", "-a", "w")
    return result.returncode, " ".join((result.stdout + result.stderr).split())


@pytest.mark.parametrize(
    ("fields", "kind"),
    [("['q', 'n']", "list"), ("'q'", "str"), ("5", "int")],
    ids=["list", "string", "number"],
)
def test_inspect_names_the_field_whose_object_fields_are_not_a_mapping(tmp_path, fields, kind):
    code, output = _inspect(tmp_path, f"array[object:{fields}]")

    assert code == 1, output
    assert (
        f"Inline schema field 'rows' gives its object fields as a {kind}, not a mapping of "
        "field names to types" in output
    ), output
    assert "has no attribute" not in output, output


def test_inspect_accepts_object_fields_that_are_a_mapping(tmp_path):
    code, output = _inspect(tmp_path, "array[object:{'q': 'string!', 'n': 'number'}]")

    assert code == 0, output
    assert "not a mapping" not in output, output
