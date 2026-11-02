"""A request that outlasts `request_timeout` fails, is retried, and the run says why.

The stub speaks the OpenAI chat API and never answers: each request waits until the
test ends. Every run is an `agac run` through the CLI against a `llamafile` action
pointed at the stub, so the timeout travels the whole way from the workflow file.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import openai
import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "hung"
STUB_HOLDS_FOR = 60.0
MAX_ATTEMPTS = 2


class _Server(ThreadingHTTPServer):
    requests: list[float]
    release: threading.Event


@pytest.fixture
def hung_server() -> Iterator[_Server]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length", 0)))
            self.server.requests.append(time.monotonic())  # type: ignore[attr-defined]
            self.server.release.wait(STUB_HOLDS_FOR)  # type: ignore[attr-defined]

        def log_message(self, *args: object) -> None:
            pass

    server = _Server(("127.0.0.1", 0), Handler)
    server.requests = []
    server.release = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)


def _project(base: Path, url: str) -> Path:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "One action against a server that never answers"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  request_timeout: 1
  retry: {{ max_attempts: {MAX_ATTEMPTS} }}
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: classify_local
    intent: "Summarise"
    model_vendor: llamafile
    model_name: local
    base_url: {url}
    schema: batch_field_rules_output
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""
    )
    page = [{"page_id": "p0", "page_content": "Page text."}]
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(page))
    return root


def test_a_request_the_server_never_answers_times_out_and_is_retried(tmp_path, hung_server):
    url = f"http://127.0.0.1:{hung_server.server_address[1]}/v1"
    root = _project(tmp_path, url)

    started = time.monotonic()
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")
    elapsed = time.monotonic() - started
    output = " ".join((result.stdout + result.stderr).split())

    # Each framework attempt is one SDK call, which retries a timeout itself first.
    assert len(hung_server.requests) == MAX_ATTEMPTS * (openai.DEFAULT_MAX_RETRIES + 1), output
    assert result.returncode != 0, output
    assert (
        f"Retry exhausted for action classify_local after {MAX_ATTEMPTS} attempts: "
        "llamafile network error: Request timed out." in output
    ), output
    assert "0 completed, 1 failed" in output, output
    assert elapsed < STUB_HOLDS_FOR / 2, output
