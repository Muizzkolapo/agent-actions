"""`model_vendor: llamafile` alone reaches a local llamafile; an `openai` action beside it does not.

Every run is an `agac run` through the CLI. Each stub server speaks the OpenAI chat API
and records the requests it was sent, so an assertion on a server's log is an assertion
on which server an action reached. The `openai` action is sent to its own stub through
`OPENAI_BASE_URL`, which the openai SDK reads for a client built without a URL: a
`llamafile` action that lost its URL would land there too.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_actions.llm.config.runtime_profiles import NO_KEY_PLACEHOLDER, RUNTIME_PROFILES
from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "runtimes"
LLAMAFILE_PORT = 8080


class _Server(ThreadingHTTPServer):
    requests: list[dict]


def _serve(port: int) -> _Server:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
            self.server.requests.append(  # type: ignore[attr-defined]
                {
                    "path": self.path,
                    "model": body.get("model"),
                    "authorization": self.headers.get("authorization"),
                    "response_format": body.get("response_format"),
                }
            )
            content = json.dumps({"summary": f"from {body.get('model')}", "exam_density": "low"})
            answer = json.dumps(
                {
                    "id": "c1",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *args: object) -> None:
            pass

    server = _Server(("127.0.0.1", port), Handler)
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def servers() -> Iterator[tuple[_Server, _Server]]:
    """A stub on llamafile's default port and one on a free port."""
    try:
        local = _serve(LLAMAFILE_PORT)
    except OSError:
        pytest.skip(f"port {LLAMAFILE_PORT} is in use")
    other = _serve(0)
    try:
        yield local, other
    finally:
        for server in (local, other):
            server.shutdown()
            server.server_close()


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)


def _url(server: _Server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/v1"


def _run(base: Path, actions: str, env: dict[str, str]) -> str:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    # The fixture's project-wide api_key (OLLAMA_API_KEY, unset here) must not reach llamafile.
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "One action on a named runtime, one on openai"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
{actions}"""
    )
    page = [{"page_id": "p0", "page_content": "Page text."}]
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(page))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    return output


def _action(name: str, vendor: str, model: str, extra: str = "") -> str:
    return f"""  - name: {name}
    intent: "Summarise"
    model_vendor: {vendor}
    model_name: {model}
    schema: batch_field_rules_output
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
{extra}"""


def test_the_llamafile_row_is_the_port_this_test_serves():
    assert RUNTIME_PROFILES["llamafile"].default_base_url == f"http://localhost:{LLAMAFILE_PORT}/v1"


def test_a_llamafile_action_and_an_openai_action_reach_their_own_servers(tmp_path, servers):
    """One test holds port 8080, so parallel workers cannot skip half of it."""
    local, other = servers

    # Positive control first: a base_url on the llamafile action is followed elsewhere,
    # so the routing assertions below can tell the two servers apart.
    _run(
        tmp_path / "control",
        _action("classify_local", "llamafile", "local", f"    base_url: {_url(other)}\n"),
        {},
    )
    assert local.requests == []
    assert [r["model"] for r in other.requests] == ["local"]
    other.requests.clear()

    actions = _action("classify_local", "llamafile", "local") + _action(
        "summarize_cloud", "openai", "gpt-4o-mini", "    api_key: OPENAI_API_KEY\n"
    )
    _run(tmp_path / "mixed", actions, {"OPENAI_API_KEY": "sk-test", "OPENAI_BASE_URL": _url(other)})

    assert [r["model"] for r in local.requests] == ["local"]
    assert [r["model"] for r in other.requests] == ["gpt-4o-mini"]
    assert local.requests[0]["path"] == "/v1/chat/completions"
    assert local.requests[0]["authorization"] == f"Bearer {NO_KEY_PLACEHOLDER}"
    assert other.requests[0]["authorization"] == "Bearer sk-test"
    sent = local.requests[0]["response_format"]
    assert sent["type"] == "json_schema"
    assert set(sent["json_schema"]) == {"name", "schema"}
