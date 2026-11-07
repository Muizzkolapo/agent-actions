"""`agac inspect` and `agac run` refuse a schema file that does not exist, before any action.

Inspect passed it. Run spent on the action upstream and then failed every record of the
action naming the schema; a tool naming one ran and succeeded with no schema checked.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

PAGES = [{"page_id": "p1", "page_content": "alpha text"}]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "A schema file that does not exist"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: {{ summary: string }}
    prompt: $w.Summarize
    context_scope: {{ observe: [source.page_content] }}
  - name: classify
    intent: "Classify"
    dependencies: [summarize]
    schema: {llm_schema}
    prompt: $w.Classify
    context_scope: {{ observe: [summarize.summary] }}
  - name: tag
    kind: tool
    intent: "Tag"
    impl: missing_schema_tag
    schema: {tool_schema}
    context_scope: {{ observe: [source.page_id] }}
"""

_PROMPTS = """\
{prompt Summarize}
Summarise.
{{ source.page_content }}
{end_prompt}

{prompt Classify}
Classify.
{{ summarize.summary }}
{end_prompt}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def missing_schema_tag(data: dict[str, Any]) -> dict[str, Any]:
    return {"tag": "t"}
"""

_SCHEMA = "name: {name}\nfields:\n  - id: {field}\n    type: string\n"


def _project(tmp_path: Path, *, with_files: bool) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(
        _WORKFLOW.format(llm_schema="ms_label", tool_schema="ms_tag")
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / "w.md").write_text(_PROMPTS)
    (root / "tools" / "w").mkdir(parents=True)
    (root / "tools" / "w" / "missing_schema_tag.py").write_text(_TOOL)
    (root / "schema" / "w").mkdir(parents=True)
    if with_files:
        for name, field in (("ms_label", "label"), ("ms_tag", "tag")):
            (root / "schema" / "w" / f"{name}.yml").write_text(
                _SCHEMA.format(name=name, field=field)
            )
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _prompt_traces(project: Path) -> int:
    store = project / "agent_workflow" / "w" / "agent_io" / "store"
    dbs = list(store.glob("*.db")) if store.exists() else []
    if not dbs:
        return 0
    con = sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True)
    try:
        return con.execute("select count(*) from prompt_trace").fetchone()[0]
    finally:
        con.close()


@pytest.mark.parametrize("command", [("inspect",), ("run", "--fresh")], ids=["inspect", "run"])
def test_both_commands_refuse_each_action_naming_a_missing_schema(tmp_path, command):
    project = _project(tmp_path, with_files=False)

    result = run_agac(project, *command, "-a", "w")
    output = result.stdout + result.stderr

    assert result.returncode == 1, output
    assert "Action 'classify' names schema 'ms_label', which cannot be loaded" in output, output
    assert "Action 'tag' names schema 'ms_tag', which cannot be loaded" in output, output
    assert _prompt_traces(project) == 0, output


def test_the_same_workflow_runs_when_the_schema_files_exist(tmp_path):
    project = _project(tmp_path, with_files=True)

    inspected = run_agac(project, "inspect", "-a", "w")
    ran = run_agac(project, "run", "-a", "w", "--fresh")

    assert inspected.returncode == 0, inspected.stdout + inspected.stderr
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert _prompt_traces(project) == 2
