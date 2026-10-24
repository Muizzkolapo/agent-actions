"""A first action reads a staged spreadsheet row by its column names (1518).

`observe: [source.item_id]` on a first action over a staged `.csv` or `.xlsx` failed
with "context_scope.observe field 'source.item_id' not found in namespace 'source'",
and a prompt reading `{{ source.item_id }}` failed to render, while the same rows
staged as JSON ran and `source.*` on the same file delivered every column. The check
that renders the first record before any is sent read a spreadsheet as one text page
(`{"page_content": "<the whole file>"}`) rather than as the rows staging makes of it.
A documented `.tsv` file was refused outright as an unsupported file type.

Every case is a real `agac run` through the CLI, with the mock provider for LLM actions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows
from tests.helpers.trace_store import trace_rows

WORKFLOW = "sheet_columns"
ROWS = [{"item_id": "a1", "text": "hello"}, {"item_id": "a2", "text": "world"}]

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def echo_sheet_row(data: Any, *args) -> list[dict]:
    return [{"got": repr(data)}]
"""


def _stage(staging: Path, file_type: str, rows: list[dict]) -> None:
    columns = list(rows[0])
    if file_type == "json":
        (staging / "items.json").write_text(json.dumps(rows))
    elif file_type in ("csv", "tsv"):
        sep = "," if file_type == "csv" else "\t"
        lines = [sep.join(columns)] + [sep.join(str(r[c]) for c in columns) for r in rows]
        (staging / f"items.{file_type}").write_text("\n".join(lines) + "\n")
    elif file_type == "xlsx":
        import pandas as pd

        pd.DataFrame(rows).to_excel(staging / "items.xlsx", index=False)


def _project(base: Path, file_type: str, actions: str, run_mode: str = "online", rows=ROWS) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    staging = directory / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        'tool_path: ["tools"]\nschema_path: schema\n'
        "default_agent_config: {model_name: gpt-4o-mini}\n"
    )
    (root / "tools" / WORKFLOW / "sheet_columns_tools.py").write_text(TOOLS)
    (root / "schema" / WORKFLOW / "sheet_row_out.yml").write_text(
        "name: sheet_row_out\nfields:\n  - id: got\n    type: string\nadditionalProperties: true\n"
    )
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "Spreadsheet rows read by column"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [{file_type}] }}
actions:
{actions}"""
    )
    _stage(staging, file_type, rows)
    return root


TOOL_FIRST = """  - name: first
    kind: tool
    intent: "Echo"
    impl: echo_sheet_row
    schema: sheet_row_out
    context_scope: { observe: [source.item_id] }
"""

LLM_FIRST = """  - name: first
    intent: "Answer"
    prompt: "Answer."
    schema: { got: string }
    context_scope: { observe: [source.item_id] }
"""

LLM_PROMPT = """  - name: first
    intent: "Answer"
    prompt: "Item {{ source.item_id }} says {{ source.text }}."
    schema: { got: string }
    context_scope: { observe: [source.item_id, source.text] }
"""


def _run(root: Path, run_mode: str = "online"):
    env = {"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)
    if run_mode == "batch" and result.returncode == 0:
        # The first run submits the batch; the next collects it.
        result = run_agac(root, "run", "-a", WORKFLOW, env=env)
    return result


def _query(root: Path, sql: str) -> list[tuple]:
    store = root / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    return stored_rows(sorted(store.glob("*.db"))[0], sql)


def _stored(root: Path, action: str = "first") -> list[dict]:
    rows = _query(root, f"select data from target_data where action_name = '{action}'")
    return [record for (data,) in rows for record in json.loads(data)]


def _assert_ran(result) -> None:
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "not found in namespace" not in output, output


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("file_type", ["csv", "tsv", "xlsx"])
def test_a_first_tool_observes_one_column_of_a_staged_spreadsheet(tmp_path, file_type, run_mode):
    root = _project(tmp_path, file_type, TOOL_FIRST, run_mode)

    result = _run(root, run_mode)

    _assert_ran(result)
    seen = sorted(record["content"]["first"]["got"] for record in _stored(root))
    assert seen == [repr({"source": {"item_id": "a1"}}), repr({"source": {"item_id": "a2"}})]


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("file_type", ["csv", "xlsx"])
def test_a_first_llm_action_observes_one_column_of_a_staged_spreadsheet(
    tmp_path, file_type, run_mode
):
    root = _project(tmp_path, file_type, LLM_FIRST, run_mode)

    result = _run(root, run_mode)

    _assert_ran(result)
    stored = _stored(root)
    assert len(stored) == 2
    assert all(record["content"]["first"].get("got") for record in stored)


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("file_type", ["csv", "tsv", "xlsx"])
def test_a_first_prompt_renders_the_columns_of_each_row(tmp_path, file_type, run_mode):
    root = _project(tmp_path, file_type, LLM_PROMPT, run_mode)

    result = _run(root, run_mode)

    _assert_ran(result)
    prompts = sorted(
        prompt
        for (prompt,) in trace_rows(
            root, "select compiled_prompt from prompt_trace where action_name = 'first'"
        )
    )
    assert any("Item a1 says hello." in prompt for prompt in prompts), prompts
    assert any("Item a2 says world." in prompt for prompt in prompts), prompts


def test_a_misspelt_column_is_still_refused_before_any_record_is_sent(tmp_path):
    """The check reads the real row, so a column the file lacks still stops the run."""
    root = _project(tmp_path, "csv", TOOL_FIRST.replace("source.item_id", "source.item_idd"))

    result = _run(root)

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "source.item_idd" in output, output


def test_a_csv_column_named_like_a_namespace_stages_as_it_did(tmp_path):
    """Reading a delimited file as rows does not start refusing a column name it took.

    The reserved-name check skipped a CSV, read as lists of cells, so a `version` column
    staged; the same field in a JSON row is refused. Whether a CSV should be refused too
    is a separate decision, not a side effect of reading it as rows.
    """
    rows = [{"item_id": "a1", "version": "v1"}]
    root = _project(tmp_path, "csv", TOOL_FIRST.replace("source.item_id", "source.*"), rows=rows)

    result = _run(root)

    _assert_ran(result)
    (record,) = _stored(root)
    assert record["content"]["source"] == {"item_id": "a1", "version": "v1"}
