"""A RECORD tool that sets a required output key only inside an `if` is refused at
pre-flight however its output dict is first written (1491).

The scan read `out = {...}` as the tool's output but not `out: dict = {...}` or
`out = dict(...)`, so the same tool passed pre-flight in those spellings and then
failed every record whose branch did not fire.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "w"
PAGES = [
    {"page_id": "p1", "page_content": "has items"},
    {"page_id": "p2", "page_content": "no items"},
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
description: "A tool that sets a required key for some records"
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
  - name: producer
    kind: tool
    intent: "Produce"
    schema: producer_out
    impl: produce
    context_scope: {{ observe: [source.page_content] }}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def produce(data: Any, *args) -> dict:
    content = data["source"]["page_content"]
    {initialiser}
    {after}
    if content == "has items":
        out["items"] = "apple, pear"
    return out
"""

_SCHEMA = """\
name: producer_out
fields:
  - id: label
    type: string
  - id: items
    type: string
    required: {items_required}
additionalProperties: true
"""

INITIALISERS = {
    "plain": 'out = {"label": content}',
    "annotated": 'out: dict = {"label": content}',
    "annotated_generic": 'out: dict[str, Any] = {"label": content}',
    "dict_call": "out = dict(label=content)",
    "annotated_dict_call": "out: dict[str, Any] = dict(label=content)",
}


def _project(
    tmp_path: Path, mode: str, initialiser: str, after: str = "", items_required: bool = True
) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_WORKFLOW.format(mode=mode))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "producer_out.yml").write_text(
        _SCHEMA.format(items_required=str(items_required).lower())
    )
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "produce.py").write_text(
        _TOOL.format(initialiser=initialiser, after=after or "pass")
    )
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _dispositions(project: Path) -> list[str]:
    dbs = list((project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db"))
    if not dbs:
        return []
    con = sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition where action_name = 'producer'"
        )
        return sorted(d for (d,) in rows)
    finally:
        con.close()


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize("spelling", sorted(INITIALISERS))
def test_a_key_set_only_in_a_branch_is_refused_in_every_spelling(tmp_path, mode, spelling):
    project = _project(tmp_path, mode, INITIALISERS[spelling])

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "producer: output schema requires 'items'" in output, output
    assert "line 12 of produce.py" in output, output
    assert _dispositions(project) == [], output


@pytest.mark.parametrize(
    "after",
    [
        'out |= {"items": ""}',
        'out.update(items="")',
        'out.setdefault("items", "")',
    ],
)
def test_a_key_set_on_every_path_runs(tmp_path, after):
    project = _project(tmp_path, "online", INITIALISERS["plain"], after=after)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert _dispositions(project) == ["success", "success"], output


def test_an_optional_key_set_only_in_a_branch_runs(tmp_path):
    project = _project(tmp_path, "online", INITIALISERS["annotated"], items_required=False)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert _dispositions(project) == ["success", "success"], output
