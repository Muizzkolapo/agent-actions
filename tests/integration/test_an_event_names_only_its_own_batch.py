"""An event names a batch in `meta` only if the action that fired it sent that batch.

Submitting a batch wrote its id into the process-wide event context, so every event
fired after it, by any action, carried the last submitted id in `meta.batch_id`: a
tool action that sends no batch, and an LLM action beside the one that sent it.

Every run is an `agac run` through the CLI and the mock provider.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_step"
PAGES = [{"page_id": f"p{i}", "page_content": f"Page {i} text."} for i in range(4)]
LLM_ACTION = """  - name: {name}
    intent: "Summarise"
    schema: batch_field_rules_output
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""
TOOL_ACTION = """  - name: flatten
    kind: tool
    intent: "Flatten"
    schema: tool_action_output
    impl: flatten_pages
    context_scope: { observe: [source.page_content] }
"""
WORKFLOW_YAML = f"""name: {WORKFLOW}
description: "Two batch actions and a tool in one step"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: batch
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
{LLM_ACTION.format(name="summarize")}{LLM_ACTION.format(name="appraise")}{TOOL_ACTION}"""


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


@pytest.fixture
def batch_step(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(WORKFLOW_YAML)
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    return root


def _submit(root: Path) -> list[dict]:
    result = run_agac(
        root,
        "run",
        "-a",
        WORKFLOW,
        "--fresh",
        env={"OLLAMA_API_KEY": "not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log = root / "agent_workflow" / WORKFLOW / "agent_io" / "logs" / "events.json"
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _sender(events: list[dict]) -> dict[str, str]:
    return {
        event["data"]["batch_id"]: event["data"]["action_name"]
        for event in events
        if event["event_type"] == "BatchSubmittedEvent"
    }


def test_both_actions_send_a_batch(batch_step):
    events = _submit(batch_step)

    assert sorted(_sender(events).values()) == ["appraise", "summarize"]


def test_no_event_names_a_batch_its_action_did_not_send(batch_step):
    events = _submit(batch_step)
    sender = _sender(events)

    foreign = [
        (event["event_type"], event["meta"].get("action_name"), event["meta"]["batch_id"])
        for event in events
        if event["meta"].get("batch_id")
        and sender.get(event["meta"]["batch_id"]) != event["meta"].get("action_name")
    ]
    assert foreign == []


def test_a_tool_action_beside_batches_names_none(batch_step):
    events = _submit(batch_step)

    tagged = [
        event["event_type"]
        for event in events
        if event["meta"].get("action_name") == "flatten" and event["meta"].get("batch_id")
    ]
    assert tagged == []
