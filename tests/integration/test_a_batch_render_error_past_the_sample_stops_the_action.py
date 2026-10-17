"""Under batch, a render error no variable explains stops the action wherever its record sits.

A template can fail on one record's data with nothing missing: here `{{ extract.words //
extract.pages }}` divides by zero on the page with no pages. Online stops the action on
it. Batch renders its first prompts before anything is sent and stopped there too when
the record came first, but a record past those few failed alone, and the action
completed with the rest answered.

Each run is its own `agac` process against the agac provider mock. `extract`, a tool,
passes each page's counts through; `summarize` divides them in its prompt.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "render_stops"
PAGES = 8

_CONFIG = """\
name: render_stops
description: "A render error no variable explains, below a tool"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: extract
    kind: tool
    intent: "Extract"
    schema: render_stops_extract
    impl: render_stops_extract
    context_scope: { observe: [source.page_id, source.words, source.pages] }
  - name: summarize
    dependencies: [extract]
    run_mode: {mode}
    intent: "Summarise"
    schema: render_stops_summary
    prompt: $render_stops.Summarize
    context_scope: { observe: [extract.title, extract.words, extract.pages] }
"""

_PROMPTS = """\
# render_stops - prompt store

{prompt Summarize}
Summarise page {{ extract.title }}, about {{ extract.words // extract.pages }} words a page.
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

_SUMMARY = """\
name: render_stops_summary
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""

_EXTRACT = """\
name: render_stops_extract
fields:
  - id: title
    type: string
  - id: words
    type: integer
  - id: pages
    type: integer
additionalProperties: true
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def render_stops_extract(data: Any, *args) -> list[dict]:
    page = (data or {}).get("source", data or {})
    return [
        {"title": str(page["page_id"]), "words": int(page["words"]), "pages": int(page["pages"])}
    ]
"""


def _project(tmp_path: Path, mode: str, empty: str) -> Path:
    """Pages p0..p7; the page named *empty* has no pages."""
    root = tmp_path / f"project_{mode}_{empty}"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_CONFIG.replace("{mode}", mode))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    pages = [
        {"page_id": f"p{i}", "words": 1000, "pages": 0 if f"p{i}" == empty else 4}
        for i in range(PAGES)
    ]
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(pages))
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "render_stops_summary.yml").write_text(_SUMMARY)
    (root / "schema" / WORKFLOW / "render_stops_extract.yml").write_text(_EXTRACT)
    (root / "tools" / WORKFLOW).mkdir()
    (root / "tools" / WORKFLOW / "extract.py").write_text(_TOOL)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run(project: Path) -> tuple[int, str]:
    result = run_agac(
        project,
        "run",
        "-a",
        WORKFLOW,
        "-u",
        "tools",
        "--fresh",
        env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    return result.returncode, result.stdout + result.stderr


def _action_disposition(project: Path) -> str | None:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select disposition from record_disposition "
            "where action_name = ? and record_id = '__node__'",
            ("summarize",),
        ).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def _assert_the_action_stopped(project: Path, code: int, output: str) -> None:
    assert code != 0, output
    assert "Failed actions: summarize" in output, output
    assert "division" in output or "undefined variables" in output, output
    assert _action_disposition(project) == "failed", output


def test_online_stops_the_action_on_a_record_past_the_first_few(tmp_path):
    """The behaviour batch is held to."""
    project = _project(tmp_path, "online", empty="p6")

    code, output = _run(project)

    _assert_the_action_stopped(project, code, output)


@pytest.mark.parametrize("empty", ["p0", "p6"], ids=["first_record", "past_the_first_few"])
def test_batch_stops_the_action_and_sends_nothing(tmp_path, empty):
    project = _project(tmp_path, "batch", empty=empty)

    code, output = _run(project)

    _assert_the_action_stopped(project, code, output)
    assert "batch job submitted" not in output, output
    assert not list((project / ".agac" / "batch_state").glob("*.json")), output
