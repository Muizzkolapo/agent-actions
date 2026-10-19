"""A context_scope entry reading a key under a scalar, or one a closed object lacks, is refused.

Measured: `observe: [prep.text.sub]` failed every record at run time, and
`passthrough: [prep.text.sub]` forwarded nothing and exited 0, once the analyzer's own
context-scope check was gone. `prep.meta.x` on an object listing `x` still runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "w"

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "A nested context_scope entry"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: prep
    kind: tool
    intent: "Prepare"
    impl: fix1536b_prep
    schema:
      type: object
      properties:
        text: {{ type: string }}
        meta:
          type: object
          properties:
            x: {{ type: integer }}
          additionalProperties: false
    context_scope: {{ observe: [source.page_content] }}
  - name: cons
    kind: tool
    intent: "Consume"
    impl: fix1536b_cons
    dependencies: [prep]
    schema: {{ seen: string }}
    context_scope:
      observe: [prep.text]
{extra}
"""

_TOOL = """\
import json
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def fix1536b_prep(data: dict[str, Any]) -> dict[str, Any]:
    return {"text": "t", "meta": {"x": 1}}


@udf_tool()
def fix1536b_cons(data: dict[str, Any]) -> dict[str, Any]:
    return {"seen": json.dumps(data, default=str, sort_keys=True)}
"""


def _project(tmp_path: Path, extra: str) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_WORKFLOW.format(extra=extra))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "one"}])
    )
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text("")
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "fix1536b_tools.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


@pytest.mark.parametrize(
    ("extra", "says"),
    [
        ("      passthrough: [prep.text.sub]", "reads 'sub' under 'text', which is string"),
        (
            "      passthrough: [prep.meta.nosuch]",
            "reads 'nosuch' under 'meta', whose schema does not list it",
        ),
    ],
)
def test_a_passthrough_that_forwards_nothing_is_refused(tmp_path, extra, says):
    project = _project(tmp_path, extra)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert says in output, output


def test_a_key_the_closed_object_lists_still_runs(tmp_path):
    project = _project(tmp_path, "      passthrough: [prep.meta.x]")

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "1 completed" in output or "2 completed" in output, output
