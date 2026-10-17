"""A model call's events name the action that made it, however many actions run at once.

`events.json` labelled every event with a process-wide "current action". The parallel
runner set it for each action of a step before any of them ran, so every event of the
step, model calls included, carried the last action's name: a tool action that makes
no call was credited with all of them. `data.action_name` on the LLM events was empty.

Every run is an `agac run` through the CLI and the mock provider.
"""

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "one_step"
PAGES = [{"page_id": f"p{i}", "page_content": f"Page {i} text."} for i in range(4)]
LLM_ACTION = """  - name: {name}
    intent: "Summarise"
    schema: batch_field_rules_output
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content{observe}] }}{dependencies}
"""
TOOL_ACTION = """  - name: flatten
    kind: tool
    intent: "Flatten"
    schema: tool_action_output
    impl: flatten_pages
    context_scope: { observe: [source.page_content] }
"""
HEADER = f"""name: {WORKFLOW}
description: "Model calls and a tool"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
"""


def _project(base: Path, actions: str) -> Path:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(HEADER + actions)
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    return root


def _run(root: Path) -> list[dict]:
    result = run_agac(
        root,
        "run",
        "-a",
        WORKFLOW,
        "--fresh",
        env={"OLLAMA_API_KEY": "not-used"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log = root / "agent_workflow" / WORKFLOW / "agent_io" / "logs" / "events.json"
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _calls(events: list[dict], where: str) -> Counter:
    """LLM request events counted by the action name each carries in `meta` or `data`."""
    return Counter(
        event[where].get("action_name")
        for event in events
        if event["event_type"] == "LLMRequestEvent"
    )


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


@pytest.fixture
def one_step(tmp_path):
    """Two LLM actions and a tool action, all reading the source, so they share a step."""
    actions = (
        TOOL_ACTION
        + LLM_ACTION.format(name="appraise", observe="", dependencies="")
        + LLM_ACTION.format(name="summarize", observe="", dependencies="")
    )
    return _project(tmp_path, actions)


@pytest.fixture
def chain(tmp_path):
    """The same actions one after another, so the run is sequential."""
    actions = LLM_ACTION.format(name="appraise", observe="", dependencies="") + LLM_ACTION.format(
        name="summarize",
        observe=", appraise.summary",
        dependencies="\n    dependencies: [appraise]",
    )
    return _project(tmp_path, actions)


def test_actions_of_one_step_each_own_their_model_calls(one_step):
    events = _run(one_step)

    assert _calls(events, "meta") == {"appraise": 4, "summarize": 4}


def test_a_tool_action_beside_model_calls_is_credited_with_none(one_step):
    events = _run(one_step)

    assert "flatten" not in _calls(events, "meta")


def test_every_event_an_action_fires_carries_its_name(one_step):
    events = _run(one_step)

    started = {
        event["data"]["action_name"]
        for event in events
        if event["event_type"] in ("ActionStartEvent", "ActionCompleteEvent")
        and event["meta"].get("action_name") != event["data"]["action_name"]
    }
    assert started == set()


def test_the_llm_event_data_names_the_action(one_step):
    events = _run(one_step)

    assert _calls(events, "data") == {"appraise": 4, "summarize": 4}


def test_a_sequential_run_names_each_call_in_meta_and_data(chain):
    events = _run(chain)

    assert _calls(events, "meta") == {"appraise": 4, "summarize": 4}
    assert _calls(events, "data") == {"appraise": 4, "summarize": 4}
