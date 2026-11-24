"""A pre-flight refusal names the workflow on every command that runs pre-flight."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
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
description: "w"
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
    schema: {schema}
{guard}    context_scope: {{ observe: [source.page_id]{seed} }}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def pick_rows(data: dict[str, Any]) -> dict[str, Any]:
    return {"rows": ""}
"""

_REFUSALS = {
    "missing-schema": (
        {"schema": "no_such_schema"},
        "names schema 'no_such_schema', which cannot be loaded",
    ),
    "invalid-guard": (
        {"guard": "    guard: { condition: 'source.page_id ==', on_false: filter }\n"},
        "invalid guard condition 'source.page_id =='",
    ),
    "missing-seed-folder": (
        {"seed": ", seed: { conf: $file:conf.json }"},
        "Seed data directory not found",
    ),
}

_ROUTES = {
    "inspect": ("inspect", "-a", "w"),
    "inspect-action": ("inspect", "action", "-a", "w", "pick"),
    "inspect-context": ("inspect", "context", "-a", "w", "pick"),
    "expect-list": ("expect", "list", "-a", "w"),
    "schema": ("schema", "-a", "w"),
    "dispositions": ("dispositions", "-a", "w"),
    "retry": ("retry", "-a", "w"),
    "run": ("run", "-a", "w"),
}


def _project(tmp_path: Path, refusal: str | None) -> Path:
    fields = {"schema": "{ rows: string }", "guard": "", "seed": ""}
    if refusal is not None:
        fields.update(_REFUSALS[refusal][0])
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(_WORKFLOW.format(**fields))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "a"}])
    )
    (root / "prompt_store").mkdir()
    (root / "templates").mkdir()
    (root / "schema" / "w").mkdir(parents=True)
    (root / "tools" / "w").mkdir(parents=True)
    (root / "tools" / "w" / "pick_rows.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    # As a run leaves it: `dispositions` and `retry` refuse a workflow with no store
    # before pre-flight runs.
    (workflow / "agent_io" / "store").mkdir()
    store = SQLiteBackend(str(workflow / "agent_io" / "store" / "w.db"), workflow_name="w")
    store.initialize()
    store.close()
    return root


def _output(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


@pytest.mark.parametrize("route", sorted(_ROUTES))
@pytest.mark.parametrize("refusal", sorted(_REFUSALS))
def test_a_preflight_refusal_names_the_workflow(tmp_path, refusal, route):
    result = run_agac(_project(tmp_path, refusal), *_ROUTES[route])
    output = _output(result)

    assert result.returncode == 1, output
    assert _REFUSALS[refusal][1] in output, output
    assert "agent 'w'" in output, output
    assert "Agent: w " in output, output
    assert "'unknown'" not in output, output
    assert "Operation Failed: command" not in output, output


def test_the_same_workflow_without_a_defect_passes_preflight(tmp_path):
    result = run_agac(_project(tmp_path, None), "inspect", "-a", "w")

    assert result.returncode == 0, _output(result)
    assert "pick" in _output(result)
