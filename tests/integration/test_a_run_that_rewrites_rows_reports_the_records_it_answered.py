"""A run that replaces the rows an action already stores reports the records it answered.

The completion line and `ActionCompleteEvent.record_count` are the records this
execution wrote. They were worked out as the action's stored row count after the run
minus the count before, so a run that replaced N stored rows reported 0: `agac run
--rerun`, and `agac retry`.

Every run is an `agac run` or `agac retry` through the CLI, executor, store and mock
provider.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.llm.providers.agac.client import AgacClient

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ACTION = "summarize"
PUBLISHER = "publish"
PAGES = {
    "pages1.json": ["Page alpha.", "Page beta."],
    "pages2.json": ["Page gamma.", "Page delta."],
}
PUBLISH_ACTION = f"""  - name: {PUBLISHER}
    intent: "Publish"
    dependencies: [{ACTION}]
    schema: batch_field_rules_output
    prompt: $p.Publish
    context_scope: {{ observe: [{ACTION}.summary] }}
    expect: {{ repair: none }}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Four pages in two files, answered by the mock provider, and a reader."""
    from agent_actions.utils import path_utils

    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    config = _config(root)
    config.write_text(
        config.read_text()
        .replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
        .rstrip("\n")
        + "\n"
        + PUBLISH_ACTION
    )
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging)
    staging.mkdir()
    for name, pages in PAGES.items():
        (staging / name).write_text(json.dumps([{"page_content": page} for page in pages]))
    monkeypatch.chdir(root)
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.setattr(path_utils, "_global_path_manager", path_utils._global_path_manager)
    return root


@pytest.fixture
def online(project):
    config = _config(project)
    config.write_text(config.read_text().replace("run_mode: batch", "run_mode: online"))
    return project


def _config(root):
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _run(*args):
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])
    assert result.exit_code == 0, result.output
    return result


def _completions(root) -> dict[str, int]:
    """The record_count of each action's last ActionCompleteEvent across the kept run logs."""
    logs = root / "agent_workflow" / WORKFLOW / "agent_io" / "logs"
    rotated = sorted(logs.glob("events.*.json"), key=lambda p: -int(p.name.split(".")[1]))
    events = [
        json.loads(line)
        for log in [*rotated, logs / "events.json"]
        for line in log.read_text().splitlines()
        if line.strip()
    ]
    return {
        event["data"]["action_name"]: event["data"]["record_count"]
        for event in events
        if event["event_type"] == "ActionCompleteEvent"
    }


def test_a_first_run_reports_the_records_it_stored(online):
    _run("--fresh")

    assert _completions(online) == {ACTION: 4, PUBLISHER: 4}


def test_a_rerun_reports_the_records_it_answered_again(online):
    _run("--fresh")

    result = _run("--rerun", ACTION)

    assert _completions(online) == {ACTION: 4, PUBLISHER: 4}
    assert f"✓ {ACTION} 4 records" in " ".join(result.output.split())


def test_a_retry_reports_only_the_record_it_answered(online, monkeypatch):
    answer = AgacClient.call_json
    refused = {"on": True}

    def beta_is_refused(api_key, agent_config, prompt_config, context_data, schema):
        if refused["on"] and "Page beta." in json.dumps([prompt_config, context_data], default=str):
            raise ValueError("the provider refused this page")
        return answer(api_key, agent_config, prompt_config, context_data, schema)

    monkeypatch.setattr(AgacClient, "call_json", staticmethod(beta_is_refused))
    CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    refused["on"] = False

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert _completions(online)[ACTION] == 1
    assert "✓ summarize 1 record" in " ".join(result.output.split())


def _run_batch_to_completion(*args):
    """A batch action is submitted by one run and collected by the next."""
    for attempt in range(3):
        result = _run(*(args if attempt == 0 else ()))
    return result


def test_a_batch_rerun_reports_the_records_it_collected(project):
    _run_batch_to_completion("--fresh")
    assert _completions(project) == {ACTION: 4, PUBLISHER: 4}

    result = _run_batch_to_completion("--rerun", ACTION)

    assert _completions(project) == {ACTION: 4, PUBLISHER: 4}
    assert f"✓ {PUBLISHER} 4 records" in " ".join(result.output.split())


READER = "tally"
READER_ACTION = f"""  - name: {READER}
    kind: tool
    dependencies: [{ACTION}]
    run_mode: online
    intent: "Tally"
    schema: tool_action_output
    impl: echo_summary
    context_scope: {{ observe: [{ACTION}.summary] }}
    expect: {{ repair: none }}
"""
ECHO_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def echo_summary(data: Any, *args) -> list[dict]:
    return [{"summary": (data or {})["summarize"]["summary"], "exam_density": "low"}]
"""


def test_a_tool_action_reports_the_rows_it_stored_and_again_on_a_rerun(online):
    config = _config(online)
    config.write_text(config.read_text().rstrip("\n") + "\n" + READER_ACTION)
    (online / "tools" / WORKFLOW).mkdir(parents=True, exist_ok=True)
    (online / "tools" / WORKFLOW / "echo.py").write_text(ECHO_TOOL)

    _run("--fresh")
    assert _completions(online)[READER] == 4

    result = _run("--rerun", ACTION)

    assert _completions(online)[READER] == 4
    assert f"✓ {READER} 4 records" in " ".join(result.output.split())
