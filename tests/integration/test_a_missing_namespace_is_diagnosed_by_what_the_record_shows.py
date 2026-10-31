"""A prompt reading an upstream namespace the record cannot supply names the cause the record shows.

The render error said "Namespace 'X' is null (likely guard-filtered or guard-skipped)"
whenever a namespace the prompt read was missing, with or without a guard anywhere in
the workflow (1489). The failure stays loud; only the diagnosis changes: a guard is
named only when the record shows that guard skipping it, and an upstream output that
holds none of the observed fields is reported as that.

A prompt reading a field its namespace lacks names the namespace and the field, not
"Namespace 'summary' not found in context" (1500).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "missing_ns"

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
name: missing_ns
description: "A prompt reads an upstream field the record may not have"
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
{guard}  - name: publish
    dependencies: [note_direct]
    intent: "Publish"
    schema: out
    prompt: $missing_ns.Publish
    context_scope: {{ observe: [{observe}] }}
"""

GUARD = "    guard: { condition: \"source.text == 'one'\", on_false: skip }\n"


def _project(
    base: Path, run_mode: str, guard: str = "", observe: str = "note_direct.summary"
) -> Path:
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
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        CONFIG.format(run_mode=run_mode, guard=guard, observe=observe)
    )
    (directory / "agent_io" / "staging" / "rows.json").write_text(
        json.dumps([{"text": "one"}, {"text": "two"}])
    )
    return root


def _run(root: Path):
    return run_agac(
        root,
        "run",
        "-a",
        WORKFLOW,
        "--fresh",
        env={"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )


def _publish_failures(root: Path) -> list[str]:
    db = root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"
    with sqlite3.connect(db) as con:
        rows = con.execute(
            "select coalesce(reason, '') from record_disposition "
            "where action_name = 'publish' and disposition = 'failed'"
        ).fetchall()
    return [reason for (reason,) in rows]


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_an_upstream_output_without_the_observed_field_is_not_blamed_on_a_guard(tmp_path, run_mode):
    """No guard exists; record `two`'s tool output has `note` but not `summary`."""
    root = _project(tmp_path, run_mode, guard="")

    result = _run(root)
    output = _flat(result.stdout + result.stderr)

    assert "Namespace 'note_direct'" in output
    assert "guard" not in output.split("Namespace 'note_direct'", 1)[1][:200].lower()
    assert "none of the fields 'publish' observes from it" in output
    assert "observes: summary" in output
    assert "'note_direct' has: note" in output
    # `summary` is a field of the namespace, not a namespace nothing supplies.
    assert "Namespace 'summary' not found in context" not in output
    if run_mode == "online":
        (reason,) = _publish_failures(root)
        assert "guard" not in reason.lower()
        assert "none of the fields 'publish' observes from it" in reason


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_guard_skip_the_record_shows_is_named(tmp_path, run_mode):
    """A guard on `note_direct` skips record `two`; that skip is what the error names."""
    root = _project(tmp_path, run_mode, guard=GUARD)

    result = _run(root)
    output = _flat(result.stdout + result.stderr)

    assert (
        "Namespace 'note_direct' is null on this record: a guard on 'note_direct' skipped it"
        in output
    )
    assert "likely" not in output
    assert "Namespace 'summary' not found in context" not in output
    if run_mode == "online":
        (reason,) = _publish_failures(root)
        assert "a guard on 'note_direct' skipped it" in reason


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_field_the_namespace_lacks_is_named_with_its_namespace(tmp_path, run_mode):
    """The prompt reads `note_direct.summary`; record `two`'s output holds only `note`."""
    root = _project(tmp_path, run_mode, observe="note_direct.*")

    result = _run(root)
    output = _flat(result.stdout + result.stderr)

    assert "Namespace 'summary' not found in context" not in output
    assert "nothing supplies 'summary'" not in output
    assert "'note_direct' has no field 'summary'" in output
    # Record `two` alone fails, and its stored reason names the namespace and field.
    (reason,) = _publish_failures(root)
    assert "'note_direct' has no field 'summary' (it has: note)" in reason
