"""Records a batch retry sends again are reported with the failure that sent them, not as orphans.

Every run is an `agac run` through the CLI against a port nothing listens on: the
in-process Ollama batch really fails to connect for every record. The second run
collects that batch and submits a retry; the records then wait on it, and the
collect pass used to call them "possible orphans".
"""

import json
import shutil
import socket
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "unreachable_batch"
PAGES = [{"page_id": f"p{i}", "page_content": f"Page {i} text."} for i in range(2)]


def _refused_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _project(base: Path) -> Path:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "A batch provider nothing answers for"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: batch
  model_vendor: ollama_local
  model_name: some-model
  base_url: {_refused_url()}
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
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    return root


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def _text(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def test_records_sent_to_a_retry_are_reported_with_their_failure(tmp_path):
    root = _project(tmp_path)
    env = {"OLLAMA_API_KEY": "not-used", "COLUMNS": "400"}

    submitted = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)
    assert submitted.returncode == 0, _text(submitted)

    retried = run_agac(root, "run", "-a", WORKFLOW, env=env)
    output = _text(retried)
    assert retried.returncode == 0, output
    assert "possible orphans" not in output, output
    assert "2 record(s) wait on retry attempt 2 of 2 after their last attempt failed" in output
    assert "Failed to connect to Ollama" in output.split("wait on retry attempt")[1], output

    # The outcome is unchanged: with no attempt left, the action fails.
    exhausted = run_agac(root, "run", "-a", WORKFLOW, env=env)
    output = _text(exhausted)
    assert exhausted.returncode != 0, output
    assert "Action 'summarize' failed" in output, output
    assert "possible orphans" not in output, output
