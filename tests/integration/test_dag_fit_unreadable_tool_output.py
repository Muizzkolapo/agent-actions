"""`agac inspect` must not report a dag-fit gap for a tool whose output it cannot read.

The dag-fit pre-flight compares a tool action's required output fields with what
the tool provably emits and what upstream guarantees. Where the static reader
cannot see the tool's output keys (an annotated assignment, a helper that builds
the dict, a FILE tool that appends its outputs in a loop, a key whose value a
helper computes), it knows nothing about those fields, so warning that they
"are rejected at runtime" is a claim it cannot make. A FILE tool whose literal
output provably lacks a required field is still reported, which proves the
check ran.
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


@udf_tool
def annotated(data: Any, *args) -> dict:
    out: dict[str, Any] = {"alpha": "a"}
    out.update({"beta": "b"})
    return out


def tally(votes):
    return {"agreement": str(len(votes)), "verdict": "ok"}


@udf_tool
def helper(data: Any, *args) -> dict:
    return tally([1, 2])


def build_items():
    return [{"id": "1"}]


@udf_tool
def nested(data: Any, *args) -> dict:
    return {"items": build_items()}


@udf_tool
def direct(data: Any, *args) -> dict:
    return {"gamma": "g"}


@udf_tool(granularity=Granularity.FILE)
def filetool(data: Any, *args):
    outs = []
    for i, _ in enumerate(data):
        outs.append({"source_index": i, "data": {"written": "yes"}})
    return FileUDFResult(outputs=outs)


@udf_tool(granularity=Granularity.FILE)
def omits(data: Any, *args):
    return FileUDFResult(outputs=[{"source_index": 0, "data": {"note": "x"}}])
"""

_SCHEMAS = {
    "annotated_out": "fields:\n  - {id: alpha, type: string}\n  - {id: beta, type: string}\n",
    "helper_out": "fields:\n  - {id: agreement, type: string}\n  - {id: verdict, type: string}\n",
    "nested_out": textwrap.dedent("""\
        fields:
          - id: items
            type: array
            items:
              type: object
              properties:
                id: {type: string}
              required: [id]
        """),
    "direct_out": "fields:\n  - {id: gamma, type: string}\n",
    "filetool_out": "fields:\n  - {id: written, type: string}\n",
    "omits_out": "fields:\n  - {id: note, type: string}\n  - {id: never_written, type: string}\n",
}

_WORKFLOW = textwrap.dedent("""\
    name: wf
    description: "dag-fit on tools whose output cannot be read"
    version: "0.1.0"
    defaults:
      json_mode: true
      granularity: Record
      run_mode: online
      model_vendor: agac-provider
      model_name: mock
      data_source: { type: local, folder: ./staging, file_type: [json] }
    actions:
      - {name: a_annotated, kind: tool, intent: x, schema: annotated_out, impl: annotated,
         context_scope: {observe: [source.page_content]}}
      - {name: a_helper, kind: tool, intent: x, schema: helper_out, impl: helper,
         context_scope: {observe: [source.page_content]}}
      - {name: a_nested, kind: tool, intent: x, schema: nested_out, impl: nested,
         context_scope: {observe: [source.page_content]}}
      - {name: a_direct, kind: tool, intent: x, schema: direct_out, impl: direct,
         context_scope: {observe: [source.page_content]}}
      - {name: a_file, kind: tool, intent: x, granularity: File, schema: filetool_out,
         impl: filetool, dependencies: [a_direct], context_scope: {observe: [a_direct.gamma]}}
      - {name: a_omits, kind: tool, intent: x, granularity: File, schema: omits_out,
         impl: omits, dependencies: [a_direct], context_scope: {observe: [a_direct.gamma]}}
    """)


def _project(root: Path) -> Path:
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  model_vendor: agac-provider\n  model_name: mock\n"
        'tool_path: ["tools"]\nschema_path: schema\nrequired_by_default: true\n'
    )
    for sub in ("prompt_store", "templates", "seed_data"):
        (root / sub).mkdir()
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
    assert start != -1, f"the dag-fit check did not report the omitting tool:\n{output}"
    end = output.find("Fix:", start)
    return output[start : end if end != -1 else len(output)]


def test_inspect_reports_no_gap_for_tool_output_it_cannot_read(tmp_path):
    root = _project(tmp_path)
    result = run_agac(root, "inspect", "-a", "wf")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output

    block = _dag_fit_block(output)
    assert "a_omits: never_written" in block, block
    for unreadable in ("a_annotated", "a_helper", "a_nested", "a_file"):
        assert unreadable not in block, f"{unreadable} was reported:\n{block}"
    assert "a_direct" not in block, block
