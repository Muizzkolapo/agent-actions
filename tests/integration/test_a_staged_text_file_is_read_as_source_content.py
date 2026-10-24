"""A first action reads a staged text file's chunk as `source.content` (1522).

Staging stores each chunk of a `.txt` (or `.md`, `.html`, `.pdf`, `.docx`) file as a
record `{"content": <chunk>}`, but the check that renders the first record before any
is sent rendered a made-up `{"page_content": <the file's first 1000 characters>}`.
So `source.content` was refused before the run, and `source.page_content`, which the
docs showed, passed the check and then failed every record at run time.

The check now renders the first chunk staging makes, so `source.content` runs and
`source.page_content` is refused before anything is sent, naming `source.content`.

Every case is a real `agac run` through the CLI, with the mock provider for LLM actions.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows
from tests.helpers.trace_store import trace_rows

WORKFLOW = "staged_text"
TEXT = "Hello there. This is a short document.\n"

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def echo_chunk(data: Any, *args) -> list[dict]:
    return [{"got": repr(data)}]
"""


def _project(base: Path, actions: str, *, run_mode: str, suffix: str = "txt", text=TEXT) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    staging = directory / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    # Character splits, so chunking needs no tokenizer download.
    (root / "agent_actions.yml").write_text(
        'tool_path: ["tools"]\nschema_path: schema\n'
        "default_agent_config:\n  model_name: gpt-4o-mini\n"
        "  chunk_config: {split_method: chars, chunk_size: 2000, chunk_overlap: 10}\n"
    )
    (root / "tools" / WORKFLOW / "staged_text_tools.py").write_text(TOOLS)
    (root / "schema" / WORKFLOW / "chunk_out.yml").write_text(
        "name: chunk_out\nfields:\n  - id: got\n    type: string\nadditionalProperties: true\n"
    )
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "A staged text file read by its chunks"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [{suffix}] }}
actions:
{actions}"""
    )
    (staging / f"doc.{suffix}").write_text(text)
    return root


def _tool(field: str) -> str:
    return f"""  - name: first
    kind: tool
    intent: "Echo"
    impl: echo_chunk
    schema: chunk_out
    context_scope: {{ observe: [{field}] }}
"""


def _llm(field: str, observe: str | None = None) -> str:
    return f"""  - name: first
    intent: "Answer"
    prompt: "Text: {{{{ {field} }}}}"
    schema: {{ got: string }}
    context_scope: {{ observe: [{observe or field}] }}
"""


def _run(root: Path, run_mode: str):
    env = {"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)
    if run_mode == "batch" and result.returncode == 0:
        # The first run submits the batch; the next collects it.
        result = run_agac(root, "run", "-a", WORKFLOW, env=env)
    return result


def _query(root: Path, sql: str) -> list[tuple]:
    store = root / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    dbs = sorted(store.glob("*.db"))
    if not dbs:
        return []
    return stored_rows(dbs[0], sql)


def _stored(root: Path) -> list[dict]:
    rows = _query(root, "select data from target_data where action_name = 'first'")
    return [record for (data,) in rows for record in json.loads(data)]


def _prompts(root: Path) -> list[str]:
    sql = "select compiled_prompt from prompt_trace where action_name = 'first'"
    store = root / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    if not list(store.glob("*.db")):
        return []
    try:
        return [prompt for (prompt,) in trace_rows(root, sql)]
    except sqlite3.OperationalError:
        return []


def _assert_ran(result) -> None:
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "not found in namespace" not in output, output


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("suffix", ["txt", "md"])
def test_a_first_tool_observes_a_text_chunk_as_source_content(tmp_path, suffix, run_mode):
    root = _project(tmp_path, _tool("source.content"), run_mode=run_mode, suffix=suffix)

    result = _run(root, run_mode)

    _assert_ran(result)
    (record,) = _stored(root)
    assert record["content"]["first"]["got"] == repr({"source": {"content": TEXT}})


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_first_prompt_renders_each_chunk_of_a_text_file(tmp_path, run_mode):
    text = "".join(f"Sentence number {n} of a document long enough to split. " for n in range(60))
    root = _project(tmp_path, _llm("source.content"), run_mode=run_mode, text=text)

    result = _run(root, run_mode)

    _assert_ran(result)
    prompts = _prompts(root)
    assert len(prompts) == 2, prompts
    assert any("Text: Sentence number 0 of" in prompt for prompt in prompts), prompts
    assert any("Sentence number 59 of" in prompt for prompt in prompts), prompts


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize(
    "actions",
    [
        _tool("source.page_content"),
        _llm("source.page_content"),
        _llm("source.page_content", observe="source.*"),
    ],
    ids=["tool-observe", "llm-observe", "llm-prompt"],
)
def test_source_page_content_is_refused_before_any_record_is_sent(tmp_path, actions, run_mode):
    root = _project(tmp_path, actions, run_mode=run_mode)

    result = _run(root, run_mode)

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode != 0, output
    assert "source.page_content" in output, output
    assert "read it as source.content" in output, output
    assert _stored(root) == []
    assert _prompts(root) == []
