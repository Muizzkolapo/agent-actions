"""A guard comparing a field to a string containing "and" loads and runs (1383).

Pre-flight's field-name pre-check split the raw clause text on the word "and"
(among others) and refused the whole clause as "Invalid field names detected",
even though the word only appeared inside a quoted string literal. The guard
could never be written.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "string_literal_guard"

_SCHEMA = """\
name: string_literal_guard_page
fields:
  - id: summary
    type: string
additionalProperties: true
"""

_PROMPTS = """\
{prompt Archive}
Archive this page.
## PAGE
{{ source.page_content }}
```json
{"summary": "..."}
```
{end_prompt}
"""

_CONFIG = f"""\
name: {WORKFLOW}
description: "A guard on a string literal containing a blocklisted word"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: string_literal_guard_page
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: string_literal_guard_page
    prompt: $p.Publish
    context_scope: {{ observe: [summarize.summary, source.page_content] }}
    guard: {{ condition: 'source.page_content == "rock and roll"', on_false: filter }}
  - name: archive
    dependencies: [publish]
    intent: "Archive"
    schema: string_literal_guard_page
    prompt: ${WORKFLOW}.Archive
    context_scope: {{ observe: [publish.summary, source.page_content] }}
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_CONFIG)
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        json.dumps(
            [
                {"page_id": "p0", "page_content": "rock and roll"},
                {"page_id": "p1", "page_content": "jazz"},
            ]
        )
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "string_literal_guard_page.yml").write_text(_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _query(root: Path, sql: str, *params: str) -> list[tuple]:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def test_the_guard_loads_and_keeps_the_record_the_string_names(project):
    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh", env={"COLUMNS": "240"})
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Invalid field names detected" not in output, output

    rows = _query(
        project,
        "select record_id, disposition from record_disposition "
        "where action_name = 'publish' and record_id != '__node__'",
    )
    dispositions = {record: disposition for record, disposition in rows}
    assert set(dispositions.values()) == {"success", "filtered"}
    assert list(dispositions.values()).count("success") == 1
    assert list(dispositions.values()).count("filtered") == 1
