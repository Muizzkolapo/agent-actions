"""Records sent concurrently stop on Ctrl-C and resume without a duplicate.

Through the real CLI against a stub endpoint that holds each request: a run with
`record_concurrency: 4` is interrupted once some records are checkpointed, then run
again without `--fresh`. The stub's own request log says what was sent; the store
says what was kept.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from tests._support.agac_cli import AGAC, REPO, run_agac
from tests._support.fake_endpoint import FakeEndpoint

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "concurrency_probe"
ACTION = "classify"
ROWS = 16
WINDOW = 4


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("AGAC_RECORD_LIMIT", "AGAC_FILE_LIMIT", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def _project(base: Path) -> Path:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    project_file = root / "agent_actions.yml"
    project_file.write_text(
        project_file.read_text() + "\nendpoints:\n  lab:\n    url: ${LAB_URL}\n    auth: none\n"
    )
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / f"{ACTION}.yml").write_text(
        f"name: {ACTION}\nfields:\n  - id: label\n    type: string\n"
    )
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "One slow action with records in flight together"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  record_concurrency: {WINDOW}
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: {ACTION}
    intent: "Classify"
    model_vendor: lab
    model_name: local-7b
    schema: {ACTION}
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""
    )
    pages = [{"page_id": f"p{i:02d}", "page_content": f"Page {i}."} for i in range(ROWS)]
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(pages))
    return root


def _dispositions(root: Path) -> list[tuple[str, str]]:
    store = root / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    found = list(store.glob("*.db")) if store.exists() else []
    if not found:
        return []
    try:
        con = sqlite3.connect(f"file:{found[0]}?mode=ro", uri=True, timeout=1)
        try:
            return list(
                con.execute(
                    "select record_id, disposition from record_disposition"
                    " where action_name = ? and record_id != '__node__'",
                    (ACTION,),
                )
            )
        finally:
            con.close()
    except sqlite3.OperationalError:
        return []


def _start(root: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    merged = {**os.environ, **env, "PYTHONPATH": str(REPO)}
    return subprocess.Popen(
        [str(AGAC), "run", "-a", WORKFLOW, "--fresh"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=merged,
    )


def test_an_interrupted_concurrent_run_resumes_each_record_once(tmp_path):
    with FakeEndpoint() as lab:
        lab.delay = 0.4
        env = {"LAB_URL": lab.base_url}
        root = _project(tmp_path)

        run = _start(root, env)
        deadline = time.monotonic() + 120
        while len(_dispositions(root)) < WINDOW and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(_dispositions(root)) >= WINDOW, "no record was checkpointed in time"

        peak_before_interrupt = lab.peak_in_flight
        sent_before_interrupt = len(lab.requests)
        run.send_signal(signal.SIGINT)
        output, _ = run.communicate(timeout=60)
        sent_after_interrupt = len(lab.requests) - sent_before_interrupt
        kept = len(_dispositions(root))

        assert run.returncode == 130, output
        assert peak_before_interrupt == WINDOW
        assert sent_after_interrupt <= WINDOW
        assert kept < ROWS, "the run finished before the interrupt; slow the stub"

        sent_before_resume = len(lab.requests)
        resumed = run_agac(root, "run", "-a", WORKFLOW, env=env)
        sent_on_resume = len(lab.requests) - sent_before_resume

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    # Answers that arrived while the interrupt waited were kept, so none is sent again.
    assert sent_on_resume == ROWS - kept
    assert len(lab.requests) == ROWS
    rows = _dispositions(root)
    assert len(rows) == ROWS
    assert len({record_id for record_id, _ in rows}) == ROWS
    assert {disposition for _, disposition in rows} == {"success"}
