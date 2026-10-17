"""`agac inspect` reports a required field a tool's code does not return, whatever upstream holds.

A tool action's output schema is checked against exactly what its UDF returns.
Upstream fields reach a RECORD tool keyed by action name and a FILE tool as
input items, and `context_scope.passthrough` fields land beside the tool's own
output after it is validated; none of them supply a field the tool leaves out.
So an upstream schema that requires the same field name guarantees nothing, and
the dag-fit warning must still name the field (1492).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tests._support.agac_cli import run_agac

_TOOLS = """
from typing import Any

from agent_actions import udf_tool
from agent_actions.config.types import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult


@udf_tool(granularity=Granularity.FILE)
def file_note(data: Any, *args):
    return FileUDFResult(outputs=[{"source_index": 0, "data": {"note": "x"}}])


@udf_tool
def record_note(data: Any, *args) -> dict:
    out: dict[str, Any] = {"note": "x"}
    return out


@udf_tool
def complete(data: Any, *args) -> dict:
    return {"id": "1", "note": "x"}
"""

_SCHEMAS = {
    "extract_out": "fields:\n  - {id: id, type: string}\n  - {id: summary, type: string}\n",
    "note_out": "fields:\n  - {id: id, type: string}\n  - {id: note, type: string}\n",
    "complete_out": textwrap.dedent("""\
        fields:
          - {id: id, type: string}
          - {id: note, type: string}
          - id: tags
            type: array
            required: false
            items:
              type: object
              properties:
                label: {type: string}
              required: [label]
        """),
}

_PROMPTS = textwrap.dedent("""\
    # p

    {prompt Extract}
    Give the page an id and a summary.
    ## PAGE
    {{ source.page_content }}
    ```json
    {"id": "...", "summary": "..."}
    ```
    {end_prompt}
    """)

_WORKFLOW = textwrap.dedent("""\
    name: wf
    description: "dag-fit on a tool below an action that requires the same field"
    version: "0.1.0"
    defaults:
      json_mode: true
      granularity: Record
      run_mode: online
      model_vendor: agac-provider
      model_name: mock
      api_key: OLLAMA_API_KEY
      data_source: { type: local, folder: ./staging, file_type: [json] }
    actions:
      - {name: extract, intent: x, schema: extract_out, prompt: $p.Extract,
         context_scope: {observe: [source.page_content]}}
      - {name: a_file, kind: tool, intent: x, granularity: File, schema: note_out,
         impl: file_note, dependencies: [extract],
         context_scope: {observe: [extract.id, extract.summary]}}
      - {name: a_record, kind: tool, intent: x, schema: note_out, impl: record_note,
         dependencies: [extract], context_scope: {observe: [extract.id]}}
      - {name: a_passthrough, kind: tool, intent: x, granularity: File, schema: note_out,
         impl: file_note, dependencies: [extract],
         context_scope: {observe: [extract.summary], passthrough: [extract.id]}}
      - {name: a_declared, kind: tool, intent: x, granularity: File, schema: note_out,
         impl: file_note, dependencies: [extract], defaults: {id: ""},
         context_scope: {observe: [extract.id]}}
      - {name: a_complete, kind: tool, intent: x, schema: complete_out, impl: complete,
         dependencies: [extract], context_scope: {observe: [extract.id]}}
    """)


def _project(root: Path) -> Path:
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  model_vendor: agac-provider\n  model_name: mock\n"
        'tool_path: ["tools"]\nschema_path: schema\nrequired_by_default: true\n'
    )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    for sub in ("prompt_store", "templates", "seed_data"):
        (root / sub).mkdir()
    (root / "prompt_store" / "p.md").write_text(_PROMPTS)
    (root / "tools" / "wf").mkdir(parents=True)
    (root / "tools" / "wf" / "tools.py").write_text(_TOOLS)
    schema_dir = root / "schema" / "wf"
    schema_dir.mkdir(parents=True)
    for name, body in _SCHEMAS.items():
        (schema_dir / f"{name}.yml").write_text(f"name: {name}\n{body}")
    wf = root / "agent_workflow" / "wf"
    (wf / "agent_config").mkdir(parents=True)
    (wf / "agent_config" / "wf.yml").write_text(_WORKFLOW)
    (wf / "agent_io" / "staging").mkdir(parents=True)
    (wf / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "hello"}])
    )
    return root


def _dag_fit_block(output: str) -> str:
    start = output.find("dag-fit")
    assert start != -1, f"the dag-fit check reported nothing:\n{output}"
    end = output.find("Fix:", start)
    return output[start : end if end != -1 else len(output)]


def test_inspect_names_each_field_a_tool_does_not_return(tmp_path):
    result = run_agac(_project(tmp_path), "inspect", "-a", "wf")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output

    block = _dag_fit_block(output)
    for action, tool in (
        ("a_file", "file_note"),
        ("a_record", "record_note"),
        ("a_passthrough", "file_note"),
    ):
        line = next((ln for ln in block.splitlines() if f"{action}: id" in ln), None)
        assert line is not None, f"{action} was not reported:\n{block}"
        assert f"not returned by tool '{tool}'" in line, (
            f"the line does not name the tool:\n{block}"
        )


def test_inspect_does_not_report_what_the_tool_returns_or_declares(tmp_path):
    result = run_agac(_project(tmp_path), "inspect", "-a", "wf")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output

    block = _dag_fit_block(output)
    assert "a_declared" not in block, block
    assert "a_complete" not in block, block
    assert "note" not in block.replace("record_note", "").replace("file_note", ""), block
