"""`agac retry` counts and lists records, not the action's own failed row.

An action whose every record fails also stores a failed disposition under the
`__node__` id: a signal about the action, not a record. The retry plan counted it
among the "Records to retry" and listed it in the Failed Records table, so a
one-record workflow read as two records to retry.

Each run is an `agac` process against a local server standing in for an Ollama host:
it answers 503 until the test lets it answer, so the record's retries run out.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "one_record"
ANSWER = {"summary": "A page.", "exam_density": "low"}


@pytest.fixture
def provider() -> Iterator[tuple[ThreadingHTTPServer, str]]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length", 0)))
            if self.server.answering:  # type: ignore[attr-defined]
                status = 200
                payload = {
                    "model": "some-model",
                    "created_at": "2026-01-01T00:00:00Z",
                    "message": {"role": "assistant", "content": json.dumps(ANSWER)},
                    "done": True,
                }
            else:
                status, payload = 503, {"error": "service unavailable"}
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.answering = False  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def _project(base: Path, url: str) -> Path:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "One record, and a provider that is down"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: ollama_local
  model_name: some-model
  base_url: {url}
  retry: {{ enabled: true, max_attempts: 2 }}
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: batch_field_rules_output
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""
    )
    page = [{"page_id": "p0", "page_content": "Page text."}]
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(page))
    return root


def _exhausted(tmp_path: Path, provider) -> Path:
    _, url = provider
    project = _project(tmp_path, url)
    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "exhausted" in output, output
    return project


def _summaries(project: Path) -> list[dict]:
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return [
            row
            for path in backend.list_target_files("summarize")
            for row in backend.read_target_for_rewrite("summarize", path)
        ]
    finally:
        backend.close()


def test_the_retry_plan_counts_the_one_record_and_not_the_action(tmp_path, provider):
    project = _exhausted(tmp_path, provider)

    result = run_agac(project, "retry", "-a", WORKFLOW, "--dry-run")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Records to retry: 1" in output, output
    assert "__node__" not in output, output
    assert "exhausted_after_2_attempts" in output, output


def test_the_retry_answers_the_record_and_says_it_cleared_one(tmp_path, provider):
    project = _exhausted(tmp_path, provider)
    server, _ = provider
    server.answering = True

    result = run_agac(project, "retry", "-a", WORKFLOW)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Records to retry: 1" in output, output
    assert "__node__" not in output, output
    assert "for 1 record(s)" in output, output
    (row,) = _summaries(project)
    assert row["content"]["summarize"]["summary"] == ANSWER["summary"], row
