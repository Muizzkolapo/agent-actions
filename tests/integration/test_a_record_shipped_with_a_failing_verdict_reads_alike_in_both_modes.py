"""A record shipped with a failing verdict reads the same in both modes, and stays a success.

`on_exhausted: return_last` and `repair: none` ship the record carrying `overall_pass: false`
by design, so a guard below can filter on it. Online and batch run the same workflow through
`agac run` against the agac provider mock. In all four the record is stored `success` with
reason `expectations_failed`, the run line says it failed its checks, and the reader below
still receives it: a failed check is not a failure, and nothing is cascade-blocked.
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
WORKFLOW = "ships_failing"

_EXPECT = {
    "return_last": "{ repair: auto, max_iterations: 2, on_exhausted: return_last, "
    "expectations: [ { id: never_matches, type: matches_regex, field: summary, "
    "params: { pattern: '^NEVER_MATCHES$' } } ] }",
    "repair_none": "{ repair: none, expectations: [ { id: never_matches, type: matches_regex, "
    "field: summary, params: { pattern: '^NEVER_MATCHES$' } } ] }",
}

_CONFIG = """\
name: ships_failing
description: "A record shipped with a failing verdict"
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
    schema: ships_failing_summary
    prompt: $ships_failing.Summarize
    context_scope: { observe: [source.page_content] }
    expect: EXPECT
  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: ships_failing_published
    prompt: $ships_failing.Publish
    context_scope: { observe: [summarize.summary] }
"""

_SUMMARY = """\
name: ships_failing_summary
fields:
  - id: summary
    type: string
additionalProperties: true
"""

_PUBLISHED = """\
name: ships_failing_published
fields:
  - id: summary
    type: string
additionalProperties: true
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


def _project(tmp_path: Path, run_mode: str, policy: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _CONFIG.replace("RUN_MODE", run_mode).replace("EXPECT", _EXPECT[policy])
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in (1, 2)])
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "ships_failing_summary.yml").write_text(_SUMMARY)
    (root / "schema" / WORKFLOW / "ships_failing_published.yml").write_text(_PUBLISHED)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> str:
    """Every run's output, unwrapped, until no batch is left to collect."""
    outputs = []
    for attempt in range(8):
        args = ("--fresh",) if attempt == 0 else ()
        result = run_agac(
            project,
            "run",
            "-a",
            WORKFLOW,
            *args,
            env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        outputs.append(" ".join(output.split()))
        if "run again" not in output:
            return " ".join(outputs)
    pytest.fail(f"the workflow never stopped asking to be run again:\n{outputs[-1]}")


def _dispositions(project: Path, action: str) -> list[tuple[str, str | None]]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return sorted(
            con.execute(
                "select disposition, reason from record_disposition "
                "where action_name = ? and record_id != '__node__'",
                (action,),
            )
        )
    finally:
        con.close()


def _status(project: Path, action: str) -> str:
    status_file = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[action]["status"]


@pytest.fixture(
    params=[
        ("online", "return_last"),
        ("online", "repair_none"),
        ("batch", "return_last"),
        ("batch", "repair_none"),
    ],
    ids=lambda p: "-".join(p),
)
def finished(request, tmp_path):
    run_mode, policy = request.param
    project = _project(tmp_path, run_mode, policy)
    output = _run_to_the_end(project)
    return request.param, project, output


def test_the_record_is_a_success_that_names_its_failed_checks(finished):
    case, project, output = finished

    assert _dispositions(project, "summarize") == [("success", "expectations_failed")] * 2, (
        case,
        output,
    )
    assert _status(project, "summarize") == "completed", (case, output)


def test_the_run_line_says_the_records_failed_their_checks(finished):
    case, _, output = finished

    assert "⚠ summarize 2 records in" in output, (case, output)
    assert "— 2 failed their checks" in output, (case, output)
    assert "2 records failed their checks" in output, (case, output)


def test_the_reader_below_still_receives_the_records(finished):
    case, project, output = finished

    assert _dispositions(project, "publish") == [("success", None)] * 2, (case, output)
