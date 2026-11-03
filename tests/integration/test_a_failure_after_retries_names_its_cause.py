"""An action whose every record exhausted its retries says what the provider said (1607).

The retry service kept the last error, but the record's error read only "Retry
exhausted after N attempts" and the run's summary counted no cause for it, so the
action failed with a bare tally: "produced 0 successful records … (Found 1 files
but failed to process any.)". Run through the CLI against a port nothing listens on.
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


def _refused_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _project(base: Path, on_exhausted: str) -> Path:
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
  model_vendor: openai
  model_name: some-model
  api_key: OPENAI_API_KEY
  retry: {{ max_attempts: 2, on_exhausted: {on_exhausted} }}
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
    return root


def _failure(root: Path) -> str:
    log = root / "agent_workflow" / WORKFLOW / "agent_io" / "logs" / "events.json"
    events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    (failed,) = [e for e in events if e["event_type"] == "ActionFailedEvent"]
    return failed["data"]["error_message"]


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


@pytest.mark.parametrize("on_exhausted", ["return_last", "raise"])
def test_the_failed_action_leads_with_the_providers_error(tmp_path, on_exhausted):
    root = _project(tmp_path, on_exhausted)

    result = run_agac(
        root,
        "run",
        "-a",
        WORKFLOW,
        "--fresh",
        env={"OPENAI_API_KEY": "not-used", "OPENAI_BASE_URL": _refused_url()},
    )

    assert result.returncode != 0
    message = _failure(root)
    assert "Connection error" in message, message
    assert message.index("Connection error") < message.index("attempts"), message
