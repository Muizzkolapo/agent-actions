"""A provider that cannot be reached is retried as the action's `retry:` asks.

The ollama client turns a refused connection into a builtin `ConnectionError`, and
the gemini and cohere SDKs let `httpx.ConnectError` through. None of these was
wrapped as a `NetworkError`, so the retry service called the failure non-retriable
and gave the record up on its first attempt.

Every run is an `agac run` through the CLI against a port nothing listens on: the
connection is really refused, nothing stands in for the provider.
"""

import json
import shutil
import socket
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "unreachable"
PAGES = [{"page_id": f"p{i}", "page_content": f"Page {i} text."} for i in range(2)]
MAX_ATTEMPTS = 2

# vendor -> (extra defaults, environment) for a provider at *url*
VENDORS = {
    "ollama_local": lambda url: (f"  base_url: {url}\n", {}),
    "ollama_cloud": lambda url: (
        f"  base_url: {url}\n  api_key: OLLAMA_API_KEY\n",
        {"OLLAMA_API_KEY": "not-used"},
    ),
    "gemini": lambda url: (
        "  api_key: GEMINI_API_KEY\n",
        {"GEMINI_API_KEY": "not-used", "GOOGLE_GEMINI_BASE_URL": url},
    ),
    "cohere": lambda url: (
        "  api_key: COHERE_API_KEY\n",
        {"COHERE_API_KEY": "not-used", "CO_API_URL": url},
    ),
    "openai": lambda url: (
        "  api_key: OPENAI_API_KEY\n",
        {"OPENAI_API_KEY": "not-used", "OPENAI_BASE_URL": url},
    ),
    "anthropic": lambda url: (
        "  api_key: ANTHROPIC_API_KEY\n",
        {"ANTHROPIC_API_KEY": "not-used", "ANTHROPIC_BASE_URL": url},
    ),
    "groq": lambda url: (
        "  api_key: GROQ_API_KEY\n",
        {"GROQ_API_KEY": "not-used", "GROQ_BASE_URL": url},
    ),
}


def _refused_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _project(base: Path, vendor: str) -> tuple[Path, dict[str, str]]:
    extra, env = VENDORS[vendor](_refused_url())
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "A provider nothing answers for"
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
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    return root, env


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_a_refused_connection_is_retried_up_to_max_attempts(tmp_path, vendor):
    root, env = _project(tmp_path, vendor)

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)

    output = result.stdout + result.stderr
    assert "Non-retriable error" not in output, output
    log = root / "agent_workflow" / WORKFLOW / "agent_io" / "logs" / "events.json"
    events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    requests = [e for e in events if e["event_type"] == "LLMRequestEvent"]
    assert len(requests) == len(PAGES) * MAX_ATTEMPTS, output
    exhausted = [e for e in events if e["event_type"] == "RetryExhaustedEvent"]
    assert len(exhausted) == len(PAGES), output
