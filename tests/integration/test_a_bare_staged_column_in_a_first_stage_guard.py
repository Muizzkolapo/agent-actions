"""A first action's guard naming a staged column bare is refused before the run (1535).

A first action's record holds the staged row under `source`, so `page_content == 'two'`
resolved against nothing: the guard filtered every record and the run exited 0, with the
output silently empty. Pre-flight let it through, taking a first stage's columns to sit
at the top level. It is now refused, naming `source.page_content`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "w"
PAGES = [
    {"page_id": "p1", "page_content": "two"},
    {"page_id": "p2", "page_content": "one"},
]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "A guard on the first action"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {mode}
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: produce
    kind: tool
    intent: "Produce"
    schema: fix1535_produce_out
    impl: fix1535_produce
    context_scope: {{ observe: [source.page_content] }}
    guard: {{ condition: "{condition}", on_false: filter }}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def fix1535_produce(data: Any, *args) -> list[dict]:
    return [{"severity": "high"}]
"""

_SCHEMA = """\
name: fix1535_produce_out
fields:
  - id: severity
    type: string
"""


def _project(tmp_path: Path, condition: str, mode: str = "online", extra: str = "") -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _WORKFLOW.format(mode=mode, condition=condition) + extra
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text("")
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "fix1535_produce_out.yml").write_text(_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "fix1535_produce.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _dispositions(project: Path) -> list[str]:
    store = project / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    dbs = list(store.glob("*.db")) if store.exists() else []
    if not dbs:
        return []
    con = sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition where action_name = 'produce'"
        )
        return sorted(disposition for (disposition,) in rows)
    finally:
        con.close()


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_bare_staged_column_is_refused_naming_source(tmp_path, mode):
    project = _project(tmp_path, "page_content == 'two'", mode)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "references field 'page_content' without an action prefix" in output, output
    assert "Did you mean 'source.page_content'?" in output, output
    assert _dispositions(project) == [], output


def test_inspect_refuses_it_too(tmp_path):
    project = _project(tmp_path, "page_content == 'two'")

    result = run_agac(project, "inspect", "-a", WORKFLOW)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "Did you mean 'source.page_content'?" in output, output


def test_the_spelling_it_names_runs_and_keeps_the_matching_record(tmp_path):
    project = _project(tmp_path, "source.page_content == 'two'")

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert _dispositions(project) == ["filtered", "success"], output


_SCOPE_ONLY_CONSUMER = """\
  - name: consumer
    kind: tool
    intent: "Consume"
    schema: fix1535_produce_out
    impl: fix1535_produce
    context_scope: {{ observe: [produce.*] }}
    guard: {{ condition: "{condition}", on_false: filter }}
"""


@pytest.mark.parametrize("condition", ["produce IS NOT NULL", "severity == 'high'"])
def test_an_upstream_named_only_in_context_scope_is_not_told_to_read_source(tmp_path, condition):
    """No dependencies, but `observe: [produce.*]`: this is no first action."""
    project = _project(
        tmp_path,
        "source.page_content == 'two'",
        extra=_SCOPE_ONLY_CONSUMER.format(condition=condition),
    )

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "A first action reads its staged row" not in output, output
    if condition.startswith("produce"):
        assert "'produce' is not upstream of it through its dependencies" in output, output
    else:
        assert "Did you mean 'produce.severity'?" in output, output
