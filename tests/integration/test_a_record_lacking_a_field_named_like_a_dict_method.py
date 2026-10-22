"""A prompt reading a field named like a dict method that a record lacks fails that
record, in either run mode (1503).

Jinja read `producer.items` on a record without `items` as the dict's `items` method, so
the model was sent "<built-in method items of dict object ...>" and the record was stored
as a success. A prompt calling a dict method, as the docs' `source.get('x', 'd')` and
`ns.items()` do, still renders. What each record was sent is read back from the consumer's prompt traces.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.trace_store import trace_rows

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
description: "A producer that emits items for some records"
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
  - name: consumer
    intent: "Consume"
    dependencies: [producer]
    schema: consumer_out
    prompt: |
      {prompt}
    context_scope: {{ observe: [producer.*, source.page_content] }}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def produce(data: Any, *args) -> list[dict]:
    content = data["source"]["page_content"]
    out = {"label": content}
    if content == "has items":
        out["items"] = "apple, pear"
    return [out]
"""

_PRODUCER_SCHEMA = """\
name: producer_out
fields:
  - id: label
    type: string
  - id: items
    type: string
    required: false
additionalProperties: true
"""

_CONSUMER_SCHEMA = """\
name: consumer_out
fields:
  - id: summary
    type: string
"""


def _project(tmp_path: Path, mode: str, prompt: str) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _WORKFLOW.format(mode=mode, prompt=prompt)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "producer_out.yml").write_text(_PRODUCER_SCHEMA)
    (root / "schema" / WORKFLOW / "consumer_out.yml").write_text(_CONSUMER_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "produce.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> str:
    outputs = []
    args = ["run", "-a", WORKFLOW, "--fresh"]
    for _ in range(4):
        result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
        output = result.stdout + result.stderr
        outputs.append(output)
        assert result.returncode == 0, "\n".join(outputs)
        if "run again" not in output:
            return "\n".join(outputs)
        args = ["run", "-a", WORKFLOW]
    pytest.fail("the workflow never stopped asking to be run again:\n" + "\n".join(outputs))


def _query(project: Path, sql: str, *params: object) -> list[tuple]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return list(con.execute(sql, params))
    finally:
        con.close()


def _sent(project: Path) -> list[str]:
    rows = trace_rows(
        project,
        "select compiled_prompt from prompt_trace where action_name = 'consumer'",
    )
    return sorted(prompt for (prompt,) in rows)


def _dispositions(project: Path) -> list[tuple[str, str]]:
    rows = _query(
        project,
        "select disposition, coalesce(reason, '') from record_disposition"
        " where action_name = 'consumer'",
    )
    return sorted(rows)


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize("read", ["producer.items", "producer['items']"])
def test_a_record_missing_a_field_named_items_fails_as_a_missing_field(tmp_path, mode, read):
    project = _project(tmp_path, mode, f"List these: {{{{ {read} }}}}")

    _run_to_the_end(project)

    assert _sent(project) == ["List these: apple, pear\n"]
    (failed, succeeded) = _dispositions(project)
    assert failed[0] == "failed"
    assert "'producer' has no field 'items' (it has: label)" in failed[1]
    assert succeeded == ("success", "")


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_prompt_calling_a_dict_method_still_renders(tmp_path, mode):
    project = _project(
        tmp_path,
        mode,
        "{{ source.get('raw', source.get('page_content', '')) }} | "
        "{% for k, v in source.items() %}{{ k }}={{ v }};{% endfor %}",
    )

    _run_to_the_end(project)

    assert _sent(project) == [
        "has items | page_content=has items;",
        "no items | page_content=no items;",
    ]
    assert _dispositions(project) == [("success", ""), ("success", "")]
