"""Under batch, a record whose own prompt cannot be rendered fails alone, as online.

Before anything is sent, batch renders the first prompts of the action to stop a broken
template early. A record whose context lacks a field it observes cannot render, but that
says nothing about the template: online fails that record and answers the rest. The
rehearsal stopped the whole action on it when it came first, and `agac retry` of such a
record, which hands the action that record alone, could never finish.

Each run is its own `agac` process against the agac provider mock. `extract`, a tool,
leaves out `body` where the page has no content; `summarize` observes `extract.body`.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "render_alone"

_CONFIG = """\
name: render_alone
description: "A record that cannot render, below a tool"
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
    schema: render_alone_extract
    impl: render_alone_extract
    context_scope: { observe: [source.page_id, source.page_content] }
  - name: summarize
    dependencies: [extract]
    run_mode: {mode}
    intent: "Summarise"
    schema: render_alone_summary
    prompt: $render_alone.Summarize
    context_scope: { observe: [extract.title, extract.body] }
"""

_PROMPTS = """\
# render_alone - prompt store

{prompt Summarize}
Summarise this page.
## TITLE
{{ extract.title }}
## BODY
{{ extract.body }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

_SUMMARY = """\
name: render_alone_summary
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""

_EXTRACT = """\
name: render_alone_extract
fields:
  - id: title
    type: string
  - id: body
    type: string
    required: false
additionalProperties: true
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def render_alone_extract(data: Any, *args) -> list[dict]:
    page = (data or {}).get("source", data or {})
    out = {"title": str(page.get("page_id"))}
    if page.get("page_content"):
        out["body"] = str(page["page_content"])
    return [out]
"""


def _project(tmp_path: Path, mode: str, empty: str) -> Path:
    """Three pages, p0..p2; the page named *empty* has no content."""
    root = tmp_path / f"project_{mode}"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_CONFIG.replace("{mode}", mode))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    pages = [
        {"page_id": f"p{i}", "page_content": "" if f"p{i}" == empty else f"page {i}"}
        for i in range(3)
    ]
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(pages))
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "render_alone_summary.yml").write_text(_SUMMARY)
    (root / "schema" / WORKFLOW / "render_alone_extract.yml").write_text(_EXTRACT)
    (root / "tools" / WORKFLOW).mkdir()
    (root / "tools" / WORKFLOW / "extract.py").write_text(_TOOL)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _agac(project: Path, *args: str) -> tuple[int, str]:
    result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
    return result.returncode, result.stdout + result.stderr


def _run_to_the_end(project: Path, *first: str) -> str:
    args = first
    output = ""
    for _ in range(4):
        code, output = _agac(project, "run", "-a", WORKFLOW, "-u", "tools", *args)
        assert code == 0, output
        if "run again" not in output:
            return output
        args = ()
    pytest.fail(f"the action never stopped asking to be run again:\n{output}")


def _outcome(project: Path) -> dict[str, tuple[str, str | None]]:
    """summarize's disposition and stored state per page_id."""
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        pages = {}
        for (blob,) in stored_rows(
            db, "select data from target_data where action_name = ?", "extract"
        ):
            loaded = json.loads(blob)
            for row in loaded if isinstance(loaded, list) else [loaded]:
                pages[row["source_guid"]] = row["content"]["extract"]["title"]
        dispositions = dict(
            con.execute(
                "select record_id, disposition from record_disposition where action_name = ?",
                ("summarize",),
            ).fetchall()
        )
        states: dict[str, str] = {}
        for (blob,) in stored_rows(
            db, "select data from target_data where action_name = ?", "summarize"
        ):
            loaded = json.loads(blob)
            for row in loaded if isinstance(loaded, list) else [loaded]:
                states[row["source_guid"]] = row["_state"]
    finally:
        con.close()
    return {
        page: (dispositions.get(guid, ""), states.get(guid))
        for guid, page in sorted(pages.items(), key=lambda item: item[1])
    }


EXPECTED = {
    "p0": ("failed", "failed"),
    "p1": ("success", "processed"),
    "p2": ("success", "processed"),
}


def test_online_fails_the_record_that_cannot_render_and_answers_the_rest(tmp_path):
    """The behaviour batch is held to."""
    project = _project(tmp_path, "online", empty="p0")

    _run_to_the_end(project, "--fresh")

    assert _outcome(project) == EXPECTED


def test_batch_fails_the_record_that_cannot_render_and_answers_the_rest(tmp_path):
    """p0 comes first, so it is the first record the rehearsal renders."""
    project = _project(tmp_path, "batch", empty="p0")

    output = _run_to_the_end(project, "--fresh")

    assert _outcome(project) == EXPECTED, output
    assert "body" in output


def test_a_batch_retry_of_the_record_finishes_and_its_failure_stands(tmp_path):
    """The retry hands the action that record alone, so it is the whole rehearsal."""
    project = _project(tmp_path, "batch", empty="p1")
    _run_to_the_end(project, "--fresh")
    before = _outcome(project)
    assert before["p1"] == ("failed", "failed"), before

    code, output = _agac(project, "retry", "-a", WORKFLOW)

    assert code == 0, output
    assert "did not finish" not in output, output
    assert _outcome(project) == before
