"""A status the provider answers with for now (429, a 5xx, Anthropic's 529) is retried.

The ollama SDK raises every HTTP error as `ollama.ResponseError`, which the Ollama
mappings took for a non-retriable API error; the anthropic SDK raises 529 as
`OverloadedError`, which is not an `InternalServerError`. Either way the record was
failed at its first attempt, whatever its `retry:` asked.

Every run is an `agac run` through the CLI against a local server that answers each
request with the status: nothing stands in for the provider's SDK.
"""

import json
import shutil
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "answering"
MAX_ATTEMPTS = 2

# vendor -> (extra defaults, environment) for a provider at *url*
VENDORS = {
    "ollama_local": lambda url: (f"  base_url: {url}\n", {}),
    "ollama_cloud": lambda url: (
        f"  base_url: {url}\n  api_key: OLLAMA_API_KEY\n",
        {"OLLAMA_API_KEY": "not-used"},
    ),
    "anthropic": lambda url: (
        "  api_key: ANTHROPIC_API_KEY\n",
        {"ANTHROPIC_API_KEY": "not-used", "ANTHROPIC_BASE_URL": url},
    ),
}


@pytest.fixture
def answering() -> Iterator[tuple[ThreadingHTTPServer, str]]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length", 0)))
            body = json.dumps({"error": "busy"}).encode()
            self.send_response(self.server.status)  # type: ignore[attr-defined]
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            # The anthropic SDK would otherwise retry on its own before agac sees the error.
            self.send_header("x-should-retry", "false")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _project(base: Path, vendor: str, url: str) -> tuple[Path, dict[str, str]]:
    extra, env = VENDORS[vendor](url)
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "A provider that answers every request with one status"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: {vendor}
  model_name: some-model
{extra}  retry: {{ enabled: true, max_attempts: {MAX_ATTEMPTS} }}
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
    return root, env


def _attempts(root: Path, vendor: str, answering, status: int) -> tuple[int, str]:
    server, url = answering
    server.status = status
    project, env = _project(root, vendor, url)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh", env=env)

    output = result.stdout + result.stderr
    log = project / "agent_workflow" / WORKFLOW / "agent_io" / "logs" / "events.json"
    events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return sum(e["event_type"] == "LLMRequestEvent" for e in events), output


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


@pytest.mark.parametrize(
    ("vendor", "status"),
    [
        ("ollama_local", 429),
        ("ollama_local", 503),
        ("ollama_cloud", 429),
        ("ollama_cloud", 502),
        ("anthropic", 529),
    ],
)
def test_a_transient_status_is_retried_up_to_max_attempts(tmp_path, answering, vendor, status):
    attempts, output = _attempts(tmp_path, vendor, answering, status)

    assert "Non-retriable error" not in output, output
    assert attempts == MAX_ATTEMPTS, output


@pytest.mark.parametrize(("vendor", "status"), [("ollama_local", 400), ("ollama_local", 404)])
def test_a_refused_request_is_not_retried(tmp_path, answering, vendor, status):
    """A bad request or a model the server does not have is refused again on a retry."""
    attempts, output = _attempts(tmp_path, vendor, answering, status)

    assert "Non-retriable error" in output, output
    assert attempts == 1, output
