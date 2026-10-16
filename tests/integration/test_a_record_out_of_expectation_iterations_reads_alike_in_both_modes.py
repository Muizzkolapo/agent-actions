"""A record out of expectation iterations under `on_exhausted: fail` reads the same in both modes.

Two staged records, a field check that fails the second one it is asked about, and
`expect: {repair: retry, max_iterations: 1, on_exhausted: fail}` on `summarize` with a
reader below it. Online and batch run the same workflow through `agac run` against the agac
provider mock; only `run_mode` differs. What each leaves stored must match: the record's
disposition, and whether the action reads clean or completed with failures.
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
WORKFLOW = "exhaust_fail"

_CONFIG = """\
name: exhaust_fail
description: "A record that runs out of expectation iterations"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: RUN_MODE
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: summarize
    intent: "Summarise"
    schema: exhaust_fail_summary
    prompt: $p.Summarize
    context_scope: { observe: [source.page_content] }
    expect: { repair: retry, max_iterations: 1, on_exhausted: fail }
  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: exhaust_fail_published
    prompt: $p.Publish
    context_scope: { observe: [summarize.summary] }
"""

_SUMMARY = """\
name: exhaust_fail_summary
fields:
  - id: summary
    type: string
    expectations:
      - id: summary_ok
        type: every_other_call_fails
additionalProperties: true
"""

_PUBLISHED = """\
name: exhaust_fail_published
fields:
  - id: summary
    type: string
additionalProperties: true
"""

_CHECK = """\
from itertools import count

from agent_actions import expectation_check

_calls = count(1)


@expectation_check("every_other_call_fails")
def every_other_call_fails(value, params):
    if next(_calls) % 2 == 0:
        return False, "the second record fails"
    return True, ""
"""

_PROMPTS = """\
{prompt Summarize}
Summarise this.
## PAGE
{{ source.page_content }}
{end_prompt}

{prompt Publish}
Publish this summary.
## SUMMARY
{{ summarize.summary }}
{end_prompt}
"""


def _project(tmp_path: Path, run_mode: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _CONFIG.replace("RUN_MODE", run_mode)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in (1, 2)])
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "exhaust_fail_summary.yml").write_text(_SUMMARY)
    (root / "schema" / WORKFLOW / "exhaust_fail_published.yml").write_text(_PUBLISHED)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / "tools" / "exhaust_fail").mkdir()
    (root / "tools" / "exhaust_fail" / "checks.py").write_text(_CHECK)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> str:
    output = ""
    for attempt in range(6):
        args = ("--fresh",) if attempt == 0 else ()
        result = run_agac(
            project,
            "run",
            "-a",
            WORKFLOW,
            "-u",
            "tools",
            *args,
            env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        if "run again" not in output:
            return output
    pytest.fail(f"the workflow never stopped asking to be run again:\n{output}")


def _dispositions(project: Path, action: str) -> list[str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return sorted(
            row[0]
            for row in con.execute(
                "select disposition from record_disposition "
                "where action_name = ? and record_id != '__node__'",
                (action,),
            )
        )
    finally:
        con.close()


def _status(project: Path, action: str) -> str:
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[action]["status"]


@pytest.fixture(params=["online", "batch"])
def finished(request, tmp_path):
    project = _project(tmp_path, request.param)
    output = _run_to_the_end(project)
    return request.param, project, output


def test_the_exhausted_record_is_stored_exhausted_in_both_modes(finished):
    mode, project, output = finished

    assert _dispositions(project, "summarize") == ["exhausted", "success"], (mode, output)


def test_an_action_holding_an_exhausted_record_completes_with_failures_in_both_modes(finished):
    mode, project, output = finished

    assert _status(project, "summarize") == "completed_with_failures", (mode, output)


def test_the_reader_below_still_runs_in_both_modes(finished):
    mode, project, output = finished

    assert _status(project, "publish") in {"completed", "completed_with_failures"}, (mode, output)
