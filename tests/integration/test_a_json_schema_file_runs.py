"""A schema file written in the documented JSON Schema form runs (1346).

Pre-flight accepted the file, then record-time compilation read its contents as
inline shorthand and refused the first value that was not a string — online and
in batch — with a message about shorthand for an author who had already used a
schema file.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "json_schema_file"

_ARRAY = """\
name: candidate_facts_list
type: array
items:
  type: object
  properties:
    fact: {type: string}
    quote: {type: string}
  required: [fact, quote]
"""

_OBJECT = """\
name: json_schema_page_summary
type: object
properties:
  summary: {type: string}
  tone: {type: string}
required: [summary]
"""

_ARRAY_WITH_TOP_LEVEL_REQUIRED = """\
name: candidate_facts_list
type: array
required: [fact]
items:
  type: object
  properties:
    fact: {type: string}
"""

_PROMPTS = """\
{prompt Summarize}
Summarise this page.
## PAGE
{{ source.page_content }}
{end_prompt}
"""


def _config(schema: str, run_mode: str) -> str:
    return f"""\
name: {WORKFLOW}
description: "A schema file in JSON Schema form"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: {schema}
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""


def _project(tmp_path: Path, schema_name: str, schema_text: str, run_mode: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_config(schema_name, run_mode))
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_id": "p0", "page_content": "alpha"}])
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / f"{schema_name}.yml").write_text(schema_text)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run(root: Path, *args: str) -> tuple[int, str]:
    result = run_agac(
        root,
        "run",
        "-a",
        WORKFLOW,
        "--fresh",
        *args,
        env={"COLUMNS": "240", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    return result.returncode, result.stdout + result.stderr


def _node_disposition(root: Path) -> str:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition "
            "where action_name = 'summarize' and record_id = '__node__'"
        ).fetchall()
    finally:
        con.close()
    return rows[0][0] if rows else ""


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize(
    ("schema_name", "schema_text"),
    [("candidate_facts_list", _ARRAY), ("json_schema_page_summary", _OBJECT)],
    ids=["array_form", "object_form"],
)
def test_a_schema_file_in_json_schema_form_is_not_read_as_inline_shorthand(
    tmp_path, schema_name, schema_text, run_mode
):
    root = _project(tmp_path, schema_name, schema_text, run_mode)

    code, output = _run(root)

    assert "Inline schema field" not in output, output
    assert "inline shorthand" not in output.lower(), output
    assert code == 0, output
    assert _node_disposition(root) != "failed"


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_an_array_schema_with_a_top_level_required_list_gets_the_array_message(tmp_path, run_mode):
    root = _project(tmp_path, "candidate_facts_list", _ARRAY_WITH_TOP_LEVEL_REQUIRED, run_mode)

    code, output = _run(root)

    assert code != 0, output
    assert "has a list at top-level 'required'" in output, output
    assert "items.required" in output, output
    assert "Inline schema field" not in output, output


def _records(root: Path) -> list[dict]:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    blobs = [row[0] for row in stored_rows(db, "select data from target_data")]
    out: list[dict] = []
    for blob in blobs:
        loaded = json.loads(blob)
        out.extend(loaded if isinstance(loaded, list) else [loaded])
    return out


def test_an_object_form_schema_file_produces_records_with_its_properties(tmp_path):
    root = _project(tmp_path, "json_schema_page_summary", _OBJECT, "online")

    code, output = _run(root)

    assert code == 0, output
    records = _records(root)
    assert records, "nothing was written"
    for record in records:
        assert {"summary", "tone"} <= set(record["content"]["summarize"]), record
