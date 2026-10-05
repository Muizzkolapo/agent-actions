"""A batch action below another one sends its retry for the records its batch lost.

Each run is its own `agac run` process against the agac provider mock. The mock answers
every task it was given, so a record is lost the way a provider loses one: its task is
taken out of the submitted batch before the run that collects it.

Building the retry rebuilds the prompt, which reads the action above. Without the
workflow's action positions that rebuild refuses the action, the retry never goes out,
and the lost record ends cascade-skipped while the action reports itself complete. A
versioned action's prompt and guard also read its version, which the rebuild needs too.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "retry_below"
PAGES = 3

_CONFIG = """\
name: retry_below
description: "A batch action below another, with retry"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: batch
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: summarize
    intent: "Summarise"
    run_mode: online
    schema: retry_below_summary
    prompt: $p.Summarize
    context_scope: { observe: [source.page_content] }
  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: retry_below_summary
    prompt: $p.Publish
    context_scope: { observe: [summarize.summary] }
    retry: { enabled: true, max_attempts: 2 }
"""

_VERSIONED = _CONFIG.replace(
    """    prompt: $p.Publish
""",
    """    versions: { param: voter_id, range: [1, 1] }
    prompt: $retry_below.Vote
    guard: { condition: "version.i == 1", on_false: filter }
""",
)

# The workflow config is rendered before it is read, so `version.*` has to sit in the
# prompt store, where it is left for the prompt's own rendering.
_PROMPTS = """\
{prompt Vote}
Voter {{ version.i }} restates this summary verbatim.
## SUMMARY
{{ summarize.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

_SCHEMA = """\
name: retry_below_summary
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""


def _project(tmp_path: Path, config: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(PAGES)])
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "retry_below_summary.yml").write_text(_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


@pytest.fixture
def project(tmp_path):
    return _project(tmp_path, _CONFIG)


def _run(project: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        [str(Path(sys.executable).parent / "agac"), "run", "-a", WORKFLOW, "-u", "tools", *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    return result.returncode, result.stdout + result.stderr


def _held_batches(project: Path) -> set[Path]:
    return set((project / ".agac" / "batch_state").glob("*.json"))


def _lose_one(batch: Path) -> dict:
    """Take the first task out of a submitted batch, and hand it back."""
    held = json.loads(batch.read_text())
    lost = held["tasks"].pop(0)
    batch.write_text(json.dumps(held))
    return lost


def _tasks(batch: Path) -> list[dict]:
    return json.loads(batch.read_text())["tasks"]


def _rows(project: Path, action: str) -> dict[str, dict]:
    """The action's stored rows, keyed by the record id a batch task carries."""
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        blobs = [
            row[0]
            for row in con.execute("select data from target_data where action_name = ?", (action,))
        ]
    finally:
        con.close()
    rows: dict[str, dict] = {}
    for blob in blobs:
        loaded = json.loads(blob)
        for row in loaded if isinstance(loaded, list) else [loaded]:
            rows[row["target_id"]] = row
    return rows


def _submitted(project: Path) -> Path:
    """The first run: the action above answers online, and this one sends its batch."""
    code, output = _run(project, "--fresh")
    assert code == 0, output
    assert "run again" in output, "the fixture did not pause on its batch"
    (batch,) = _held_batches(project)
    return batch


def _collected(project: Path) -> tuple[list[list[str]], str]:
    """One run after a submission: the record ids of each batch it sent, and its output."""
    before = _held_batches(project)
    code, output = _run(project)
    assert code == 0, output
    sent = [
        [task["custom_id"] for task in _tasks(batch)] for batch in _held_batches(project) - before
    ]
    return sent, output


def _run_to_the_end(project: Path) -> None:
    output = ""
    for _ in range(4):
        code, output = _run(project)
        assert code == 0, output
        if "run again" not in output:
            return
    pytest.fail(f"the action never stopped asking to be run again:\n{output}")


def test_a_lost_record_is_sent_again(project):
    lost = _lose_one(_submitted(project))["custom_id"]

    sent, output = _collected(project)

    assert sent == [[lost]], f"no retry batch went out for the lost record:\n{output}"


def test_the_retry_asks_with_what_the_action_above_answered(project):
    """Sent at all is not enough: the retry's prompt is the one the record was first
    sent with, built from the action above's answer for it."""
    lost = _lose_one(_submitted(project))
    before = _held_batches(project)

    _, output = _collected(project)

    retries = _held_batches(project) - before
    assert len(retries) == 1, f"no retry batch went out for the lost record:\n{output}"
    (task,) = _tasks(next(iter(retries)))
    assert task["prompt"] == lost["prompt"]
    upstream = _rows(project, "summarize")[lost["custom_id"]]["content"]["summarize"]["summary"]
    assert upstream in task["prompt"], task["prompt"]


def test_the_lost_record_is_answered(project):
    lost = _lose_one(_submitted(project))["custom_id"]

    _run_to_the_end(project)

    rows = _rows(project, "publish")
    assert sorted(row["_state"] for row in rows.values()) == ["processed"] * PAGES
    assert rows[lost]["content"]["publish"]["summary"]


def test_a_record_its_retry_loses_too_is_sent_a_third_time(project):
    """The second retry is sent from the pass that collects the first, a separate
    path from the one that sends the first."""
    lost = _lose_one(_submitted(project))["custom_id"]
    before = _held_batches(project)
    sent, output = _collected(project)
    assert sent == [[lost]], f"no retry batch went out for the lost record:\n{output}"
    (retry,) = _held_batches(project) - before
    _lose_one(retry)

    sent, output = _collected(project)

    assert sent == [[lost]], f"no second retry went out for the record:\n{output}"


def test_a_versioned_action_below_another_sends_its_lost_record_again(tmp_path):
    """Its prompt and its guard read `version.i`. Rebuilt without the version, the prompt
    does not render and the guard filters the record, so no retry could go out."""
    project = _project(tmp_path, _VERSIONED)
    lost = _lose_one(_submitted(project))
    before = _held_batches(project)

    sent, output = _collected(project)

    assert sent == [[lost["custom_id"]]], f"no retry batch went out for the lost record:\n{output}"
    (retry,) = _held_batches(project) - before
    (task,) = _tasks(retry)
    assert task["prompt"] == lost["prompt"]

    _run_to_the_end(project)

    rows = _rows(project, "publish_1")
    assert sorted(row["_state"] for row in rows.values()) == ["processed"] * PAGES
