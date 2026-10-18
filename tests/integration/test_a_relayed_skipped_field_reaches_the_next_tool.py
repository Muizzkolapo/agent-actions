"""A tool relaying a skipped action's field passes its null on to the next tool (1536).

`g` skips one record; `mid` returns `g.text` as its own `text`; `cons` reads `mid.text`.
Pre-flight makes `mid.text` accept null, as `mid` reads the skipped action directly. Main
also made `cons.text` nullable, through `mid`'s passthrough of `g.text`; once that was
removed, the skipped record failed `cons`'s output schema ("at text: None") and was lost.
The null is now carried through `mid` because it returns the field it read, with or
without the passthrough.
"""

from __future__ import annotations

import json
import sqlite3
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
description: "A relay of a skipped field"
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
    impl: fix1536c_echo
    schema: {{ id: string, text: string }}
    context_scope: {{ observe: [source.id, source.page_content] }}
  - name: g
    kind: tool
    intent: "Guarded"
    impl: fix1536c_echo_prep
    dependencies: [prep]
    guard: {{ condition: "prep.id == 'a'", on_false: skip }}
    schema: {{ id: string, text: string }}
    context_scope: {{ observe: [prep.id, prep.text] }}
  - name: mid
    kind: tool
    intent: "Relay"
    impl: fix1536c_relay
    dependencies: [g]
    schema: {{ text: string }}
    context_scope:
      observe: [g.text]
{passthrough}  - name: cons
    kind: tool
    intent: "Relay again"
    impl: fix1536c_relay2
    dependencies: [mid]
    schema: {{ text: string }}
    context_scope: {{ observe: [mid.text] }}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def fix1536c_echo(data: dict[str, Any]) -> dict[str, Any]:
    src = data.get("source") or {}
    return {"id": src.get("id", ""), "text": src.get("page_content", "")}


@udf_tool()
def fix1536c_echo_prep(data: dict[str, Any]) -> dict[str, Any]:
    prep = data.get("prep") or {}
    return {"id": prep.get("id", ""), "text": prep.get("text", "")}


@udf_tool()
def fix1536c_relay(data: dict[str, Any]) -> dict[str, Any]:
    return {"text": (data.get("g") or {}).get("text")}


@udf_tool()
def fix1536c_relay2(data: dict[str, Any]) -> dict[str, Any]:
    return {"text": (data.get("mid") or {}).get("text")}
"""


def _project(tmp_path: Path, passthrough: bool) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _WORKFLOW.format(passthrough="      passthrough: [g.text]\n" if passthrough else "")
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"id": "a", "page_content": "one"}, {"id": "b", "page_content": "two"}])
    )
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text("")
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "fix1536c_tools.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


@pytest.mark.parametrize("passthrough", [True, False])
def test_the_record_the_guard_skipped_reaches_the_end(tmp_path, passthrough):
    project = _project(tmp_path, passthrough)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "Output schema validation failed" not in output, output
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition where action_name = 'cons'"
        ).fetchall()
    finally:
        con.close()
    assert sorted(d for (d,) in rows) == ["success", "success"], output
