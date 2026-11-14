"""`agac run` names an unset API key variable as unset, and a refused key as invalid."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

_WORKFLOW = """\
name: demo
description: demo
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_name: gpt-4o-mini
  model_vendor: openai
  api_key: OPENAI_API_KEY
{base_url}actions:
  - name: summarize
    intent: summarize the source
    prompt: "Summarize {{{{ source.text }}}}"
    kind: llm
    context_scope:
      observe: ["source.*"]
    schema:
      fields:
        - id: summary
          type: string
          required: true
"""

UNSET = (
    "API key environment variable 'OPENAI_API_KEY' is not set "
    "(required by action 'summarize', vendor 'openai')"
)


class _RefuseEveryKey(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps(
            {"error": {"message": "Incorrect API key provided", "code": "invalid_api_key"}}
        ).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def refusing_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RefuseEveryKey)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)


def _project(tmp_path: Path, base_url: str | None = None) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "demo"
    (workflow / "agent_config").mkdir(parents=True)
    line = f"  base_url: {base_url}\n" if base_url else ""
    (workflow / "agent_config" / "demo.yml").write_text(_WORKFLOW.format(base_url=line))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "in.json").write_text(json.dumps([{"text": "hello"}]))
    for name in ("prompt_store", "schema"):
        (root / name).mkdir()
    (root / "agent_actions.yml").write_text("version: '1.0'\nschema_path: schema\n")
    return root


def _flat(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def test_run_refuses_an_unset_key_variable_and_names_it_as_unset(tmp_path):
    result = run_agac(_project(tmp_path), "run", "-a", "demo")
    output = _flat(result)

    assert result.returncode == 1, output
    assert UNSET in output, output
    assert "Set the environment variable: export OPENAI_API_KEY=..." in output, output
    assert "Invalid Openai API key" not in output, output


def test_run_refuses_a_set_key_the_server_rejects_as_invalid(
    tmp_path, monkeypatch, refusing_server
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-refused")

    result = run_agac(_project(tmp_path, refusing_server), "run", "-a", "demo", "--verify-keys")
    output = _flat(result)

    assert result.returncode == 1, output
    assert f"API key for vendor 'openai' at {refusing_server} is invalid" in output, output
    assert f"The server at {refusing_server} rejected the key" in output, output
    assert "is not set" not in output, output
