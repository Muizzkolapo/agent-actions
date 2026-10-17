"""A prompt reading a field its namespace lacks names the namespace and the field.

For ``{{ note_direct.summary }}`` on a record whose ``note_direct`` output holds only
``note``, Jinja's error names only the attribute, and the render logged
"Namespace 'summary' not found in context ... nothing supplies 'summary'" and stored
"references undefined variables: summary" (1500). The producer's schema declares
``summary`` as optional and allows other fields, so pre-flight only warns. The
failure stays loud; only its text changes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "missing_field"

TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def make_note(data: Any, *args) -> list[dict]:
    text = str(((data or {}).get("source") or {}).get("text"))
    return [{"note": "n-" + text}] if text == "two" else [{"summary": "s-" + text}]
"""

NOTE_SCHEMA = """\
name: note
fields:
  - id: summary
    type: string
    required: false
  - id: note
    type: string
    required: false
additionalProperties: true
"""

OUT_SCHEMA = """\
name: out
fields:
  - id: summary
    type: string
"""

PROMPT = """\
{prompt Publish}
Restate {{ note_direct.summary }}
{end_prompt}
"""

CONFIG = """\
name: missing_field
description: "A prompt reads a field its upstream output may not have"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: m
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: note_direct
    kind: tool
    intent: "Note"
    schema: note
    impl: make_note
    context_scope: {{ observe: [source.text] }}
  - name: publish
    dependencies: [note_direct]
    intent: "Publish"
    schema: out
    prompt: $missing_field.Publish
    context_scope: {{ observe: [note_direct.*] }}
"""


def _project(base: Path, run_mode: str) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\n"
        'tool_path: ["tools"]\n'
    )
    (root / "schema" / WORKFLOW / "note.yml").write_text(NOTE_SCHEMA)
    (root / "schema" / WORKFLOW / "out.yml").write_text(OUT_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPT)
    (root / "tools" / WORKFLOW / "make_note.py").write_text(TOOL)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG.format(run_mode=run_mode))
    (directory / "agent_io" / "staging" / "rows.json").write_text(
        json.dumps([{"text": "one"}, {"text": "two"}])
    )
    return root


def _publish_failures(root: Path) -> list[str]:
    db = root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"
    with sqlite3.connect(db) as con:
        rows = con.execute(
            "select coalesce(reason, '') from record_disposition "
            "where action_name = 'publish' and disposition = 'failed'"
        ).fetchall()
    return [reason for (reason,) in rows]


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_field_the_namespace_lacks_is_named_with_its_namespace(tmp_path, run_mode):
    root = _project(tmp_path, run_mode)

    result = run_agac(
        root,
        "run",
        "-a",
        WORKFLOW,
        "--fresh",
        env={"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    output = " ".join((result.stdout + result.stderr).split())

    assert "Namespace 'summary' not found in context" not in output
    assert "nothing supplies 'summary'" not in output
    assert "'note_direct' has no field 'summary'" in output
    # Record `two` alone fails, and its stored reason names the namespace and field.
    (reason,) = _publish_failures(root)
    assert "'note_direct' has no field 'summary'" in reason
    assert "'note_direct' has no field 'summary' (it has: note)" in reason
