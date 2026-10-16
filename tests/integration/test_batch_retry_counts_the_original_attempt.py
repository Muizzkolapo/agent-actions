"""`retry.max_attempts` is the number of attempts in all, the original batch included.

Online reads it that way: `max_attempts: 1` is one call and no retry. Each run here is its own
`agac run` process against the agac provider mock, and a record is lost the way a provider
loses one: its task is taken out of the submitted batch before the run that collects it.
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
WORKFLOW = "retry_count"
PAGES = 3

_CONFIG = """\
name: retry_count
description: "A batch action whose lost record is retried"
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
    schema: retry_count_summary
    prompt: $p.Summarize
    context_scope: { observe: [source.page_content] }
    retry: { enabled: true, max_attempts: MAX_ATTEMPTS }
"""

_SCHEMA = """\
name: retry_count_summary
fields:
  - id: summary
    type: string
additionalProperties: true
"""


def _project(tmp_path: Path, max_attempts: int) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _CONFIG.replace("MAX_ATTEMPTS", str(max_attempts))
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(PAGES)])
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "retry_count_summary.yml").write_text(_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(
        "{prompt Summarize}\nSummarise this.\n## PAGE\n{{ source.page_content }}\n{end_prompt}\n"
    )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run(project: Path, *args: str) -> tuple[int, str]:
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
    return result.returncode, result.stdout + result.stderr


def _held_batches(project: Path) -> set[Path]:
    return set((project / ".agac" / "batch_state").glob("*.json"))


def _lose_one(batch: Path) -> str:
    """Take the first task out of a submitted batch, and hand back its record id."""
    held = json.loads(batch.read_text())
    lost = held["tasks"].pop(0)
    batch.write_text(json.dumps(held))
    return lost["custom_id"]


def _dispositions(project: Path) -> list[tuple[str, str | None]]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [
            (row[0], row[1])
            for row in con.execute(
                "select disposition, reason from record_disposition "
                "where action_name = 'summarize' and record_id != '__node__'"
            )
        ]
    finally:
        con.close()


def _collect(project: Path) -> tuple[int, list[Path], str]:
    """One run after a submission: its exit code, the batches it sent, and its output."""
    before = _held_batches(project)
    code, output = _run(project)
    return code, sorted(_held_batches(project) - before), output


def _lost_to_the_end(project: Path) -> tuple[int, str]:
    """Submit, then lose the one record from every batch sent, until a run sends none.

    Returns how many batches went out in all, the original included.
    """
    code, output = _run(project, "--fresh")
    assert code == 0, output
    (batch,) = _held_batches(project)
    _lose_one(batch)
    batches_sent = 1
    for _ in range(6):
        code, sent, output = _collect(project)
        assert code == 0, output
        if not sent:
            return batches_sent, output
        batches_sent += len(sent)
        for retry in sent:
            _lose_one(retry)
    pytest.fail(f"the record was sent again without end:\n{output}")


@pytest.mark.parametrize("max_attempts", [1, 2, 3])
def test_a_record_the_provider_never_answers_is_asked_max_attempts_times(tmp_path, max_attempts):
    project = _project(tmp_path, max_attempts)

    batches_sent, output = _lost_to_the_end(project)

    assert batches_sent == max_attempts, output
    exhausted = [reason for state, reason in _dispositions(project) if state == "exhausted"]
    assert exhausted == [f"exhausted_after_{max_attempts}_attempts"], _dispositions(project)
