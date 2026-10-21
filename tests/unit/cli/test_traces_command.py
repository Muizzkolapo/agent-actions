import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

WORKFLOW = "wf"
ACTION = "summarize"
PROMPT = "Summarise the page in one sentence.\n" * 30 + "Page alpha."


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    workflow = tmp_path / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(f"name: {WORKFLOW}\nactions: []\n")
    store = workflow / "agent_io" / "store"
    store.mkdir(parents=True)
    backend = SQLiteBackend(str(store / f"{WORKFLOW}.db"), workflow_name=WORKFLOW)
    backend.initialize()
    backend.write_prompt_trace(ACTION, "tid-1", PROMPT, llm_context='{"page": "alpha"}')
    backend.update_prompt_trace_response(ACTION, "tid-1", "Alpha in a sentence.")
    backend.write_prompt_trace(ACTION, "tid-2", "Page beta prompt.")
    backend.close()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _traces(*args):
    return CliRunner().invoke(cli, ["traces", "-w", WORKFLOW, *args])


def test_an_actions_traces_print_as_plain_text(project):
    result = _traces("-a", ACTION)

    assert result.exit_code == 0, result.output
    assert PROMPT in result.output
    assert '{"page": "alpha"}' in result.output
    assert "Alpha in a sentence." in result.output
    assert "Page beta prompt." in result.output


def test_one_records_trace_prints_alone(project):
    result = _traces("-a", ACTION, "--record", "tid-2")

    assert result.exit_code == 0, result.output
    assert "Page beta prompt." in result.output
    assert "Page alpha." not in result.output


def test_json_output_carries_the_plain_text_fields(project):
    result = _traces("-a", ACTION, "--json")

    assert result.exit_code == 0, result.output
    traces = json.loads(result.output)
    assert [t["record_id"] for t in traces] == ["tid-1", "tid-2"]
    assert traces[0]["compiled_prompt"] == PROMPT
    assert traces[0]["response_text"] == "Alpha in a sentence."


def test_an_action_with_no_traces_says_so(project):
    result = _traces("-a", "classify")

    assert result.exit_code != 0
    assert "No prompt traces for action 'classify'" in result.output
