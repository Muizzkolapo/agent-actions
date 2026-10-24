"""A staged `.json` file that starts with a UTF-8 byte order mark stages (1537).

`FileReader._read_json` read the file as `utf-8`, so a file saved with a byte order
mark (as some editors and Windows tools write it) failed with "Unexpected UTF-8 BOM
(decode using utf-8-sig)". It now reads `utf-8-sig`, as a staged CSV does (1521),
and the records stage as if the mark were not there.

Every case is a real `agac run` through the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows
from tests.helpers.trace_store import trace_rows

WORKFLOW = "bom_json"
ROWS = [{"title": "first row"}, {"title": "second row"}]

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def bom_json_echo(data: Any, *args) -> list[dict]:
    return [{"got": repr(data)}]
"""


def _project(base: Path, run_mode: str, document: bytes) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    staging = directory / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        'tool_path: ["tools"]\nschema_path: schema\n'
        "default_agent_config:\n  model_name: gpt-4o-mini\n"
    )
    (root / "tools" / WORKFLOW / "bom_json_tools.py").write_text(TOOLS)
    (root / "schema" / WORKFLOW / "echo_out.yml").write_text(
        "name: echo_out\nfields:\n  - id: got\n    type: string\nadditionalProperties: true\n"
    )
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "A staged JSON file with a byte order mark"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: first
    kind: tool
    intent: "Echo"
    impl: bom_json_echo
    schema: echo_out
    context_scope: {{ observe: [source.title] }}
  - name: second
    intent: "Answer"
    prompt: "Title: {{{{ source.title }}}}"
    schema: {{ answer: string }}
    dependencies: [first]
    context_scope: {{ observe: [first.got, source.title] }}
"""
    )
    (staging / "rows.json").write_bytes(document)
    return root


def _run(root: Path, run_mode: str):
    env = {"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)
    if run_mode == "batch" and result.returncode == 0:
        # The first run submits the batch; the next collects it.
        result = run_agac(root, "run", "-a", WORKFLOW, env=env)
    return result


def _stored(root: Path, action: str) -> list[dict]:
    store = root / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    dbs = sorted(store.glob("*.db"))
    if not dbs:
        return []
    rows = stored_rows(dbs[0], "select data from target_data where action_name = ?", action)
    return [record for (data,) in rows for record in json.loads(data)]


def _prompts(root: Path) -> list[str]:
    sql = "select compiled_prompt from prompt_trace where action_name = 'second'"
    return [prompt for (prompt,) in trace_rows(root, sql)]


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("indent", [None, 2], ids=["compact", "indented"])
def test_a_staged_json_file_with_a_byte_order_mark_stages_its_rows(tmp_path, run_mode, indent):
    document = "\ufeff" + json.dumps(ROWS, indent=indent)
    root = _project(tmp_path, run_mode, document.encode("utf-8"))

    result = _run(root, run_mode)

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output
    assert "BOM" not in output, output
    got = sorted(record["content"]["first"]["got"] for record in _stored(root, "first"))
    assert got == sorted(repr({"source": {"title": row["title"]}}) for row in ROWS)
    assert len(_stored(root, "second")) == 2, output
    assert sorted(_prompts(root)) == ["Title: first row", "Title: second row"]


def test_the_mark_does_not_change_a_record_s_identity(tmp_path):
    plain = _project(tmp_path / "plain", "online", json.dumps(ROWS).encode("utf-8"))
    marked = _project(tmp_path / "marked", "online", ("\ufeff" + json.dumps(ROWS)).encode())

    assert _run(plain, "online").returncode == 0
    assert _run(marked, "online").returncode == 0

    def guids(root: Path) -> list[str]:
        return sorted(record["source_guid"] for record in _stored(root, "first"))

    assert guids(marked) == guids(plain)
