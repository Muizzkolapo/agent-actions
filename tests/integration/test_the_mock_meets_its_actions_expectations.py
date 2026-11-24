"""A run against the agac mock meets the action's expectations, online and in a batch.

`extract` declares a `matches_regex` rule and an `accepted_values` rule under
`repair: auto`. The mock reads both, so every record passes on its first generation: no
repair round runs and no record runs out of iterations. `check` observes
`extract.invoice_id` and declares an `invoice_id` of its own, so it carries the upstream
value rather than a fresh one. `grade` declares a rule its schema's `enum` contradicts: the
run still completes, and the mock says once which field it could not satisfy.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

WORKFLOW = "invoices"

_CONFIG = """\
name: invoices
description: "Rules the mock must meet"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: RUN_MODE
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: extract
    intent: "Extract the invoice"
    schema: extract
    prompt: $invoices.Extract
    context_scope: { observe: [source.page_content] }
    expect:
      repair: auto
      max_iterations: 3
      on_exhausted: fail
      expectations:
        - id: id_shape
          type: matches_regex
          field: invoice_id
          params: { pattern: '^INV-[0-9]{4}$' }
        - id: currency_known
          type: accepted_values
          field: currency
          params: { values: [EUR, USD, GBP] }
  - name: check
    dependencies: [extract]
    intent: "Check the invoice"
    schema: check
    prompt: $invoices.Check
    context_scope: { observe: [extract.invoice_id, extract.currency] }
  - name: grade
    dependencies: [extract]
    intent: "Grade the invoice"
    schema: grade
    prompt: $invoices.Grade
    context_scope: { observe: [extract.currency] }
    expect:
      repair: none
      expectations:
        - id: level_known
          type: accepted_values
          field: level
          params: { values: [urgent] }
"""

_SCHEMAS = {
    "extract": """\
name: extract
fields:
  - id: invoice_id
    type: string
  - id: currency
    type: string
  - id: total
    type: number
""",
    "check": """\
name: check
fields:
  - id: invoice_id
    type: string
  - id: note
    type: string
""",
    "grade": """\
name: grade
fields:
  - id: level
    type: string
    enum: [low, high]
""",
}

_PROMPTS = """\
{prompt Extract}
Extract the invoice.
{end_prompt}

{prompt Check}
Check the invoice.
{end_prompt}

{prompt Grade}
Grade the invoice.
{end_prompt}
"""

_UNMET = "could not meet every constraint on action 'grade' field 'level'"


def _project(tmp_path: Path, run_mode: str) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _CONFIG.replace("RUN_MODE", run_mode)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"invoice {i}"} for i in range(1, 5)])
    )
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    for name, text in _SCHEMAS.items():
        (root / "schema" / WORKFLOW / f"{name}.yml").write_text(text)
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / "tools").mkdir()
    (root / "seed_data").mkdir()
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  api_key: OLLAMA_API_KEY\n  model_name: mock\n"
        'tool_path: ["tools"]\nschema_path: schema\nseed_data_path: seed_data\n'
    )
    return root


def _run_to_the_end(project: Path) -> tuple[int, str]:
    output = ""
    code = 1
    for attempt in range(8):
        args = ("--fresh",) if attempt == 0 else ()
        result = run_agac(
            project,
            "run",
            "-a",
            WORKFLOW,
            *args,
        )
        code = result.returncode
        output += result.stdout + result.stderr
        if "run again" not in result.stdout + result.stderr:
            break
    return code, output


def _db(project: Path) -> Path:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    return db


def _records(project: Path, action: str) -> list[dict]:
    records = []
    for name, blob in stored_rows(_db(project), "select action_name, data from target_data"):
        if name == action:
            records += [record["content"] for record in json.loads(blob)]
    return records


def _query(project: Path, sql: str) -> list[tuple]:
    con = sqlite3.connect(f"file:{_db(project)}?mode=ro", uri=True)
    try:
        return list(con.execute(sql))
    finally:
        con.close()


@pytest.fixture(scope="module", params=["online", "batch"])
def run(request, tmp_path_factory):
    project = _project(tmp_path_factory.mktemp(request.param), request.param)
    code, output = _run_to_the_end(project)
    return request.param, project, code, output


def test_the_run_completes(run):
    mode, _, code, output = run

    assert code == 0, (mode, output)


def test_every_extracted_record_passes_its_rules(run):
    mode, project, _, output = run
    verdicts = [record["extract"]["expect"] for record in _records(project, "extract")]

    assert len(verdicts) == 4, (mode, output)
    assert all(verdict["overall_pass"] for verdict in verdicts), (mode, verdicts)


def test_no_record_runs_out_of_iterations(run):
    mode, project, _, _ = run
    dispositions = _query(
        project,
        "select disposition from record_disposition "
        "where action_name = 'extract' and record_id != '__node__'",
    )

    assert sorted(d for (d,) in dispositions) == ["success"] * 4, (mode, dispositions)


def test_no_repair_round_runs(run):
    mode, project, _, _ = run
    attempts = _query(project, "select attempt from prompt_trace where action_name = 'extract'")

    assert sorted(a for (a,) in attempts) == [0] * 4, (mode, attempts)


def test_an_observed_upstream_id_is_carried_downstream(run):
    mode, project, _, _ = run
    extracted = sorted(r["extract"]["invoice_id"] for r in _records(project, "extract"))
    checked = sorted(r["check"]["invoice_id"] for r in _records(project, "check"))

    assert len(extracted) == 4 and checked == extracted, (mode, checked, extracted)


def test_a_contradiction_is_named_once_and_the_action_still_runs(run):
    mode, project, _, output = run
    graded = [r["grade"]["level"] for r in _records(project, "grade")]
    events = project / "agent_workflow" / WORKFLOW / "agent_io" / "logs" / "events.json"

    assert len(graded) == 4 and set(graded) <= {"low", "high"}, (mode, graded)
    assert events.read_text().count(_UNMET) == 1, (mode, output)
