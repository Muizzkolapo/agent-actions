"""A record with no source_guid is refused before the action below is asked about it.

Driven through `agac run` against the real store, as such a record arises: a row the
action above stored loses its source_guid, and the action below is edited, so it runs
again over that row. The model is the provider mock, and the tool a local one that
notes each call.
"""

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    WORKFLOW,
    _backend,
    project,  # noqa: F401
)

BELOW = "ask"

ASK = """  - name: ask
    dependencies: [flatten]
    intent: "Ask"
    model_vendor: agac-provider
    model_name: mock
    schema: tool_action_output
    prompt: $ask.Ask
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""

ASK_PROMPT = """{prompt Ask}
%s
## SUMMARY
{{ flatten.summary }}
{end_prompt}
"""

NOTED_TOOL = """import json
from typing import Any

from agent_actions import udf_tool


@udf_tool
def note_and_tag(data: Any, *args) -> list[dict]:
    with open("calls.jsonl", "a") as calls:
        calls.write(json.dumps(data) + "\\n")
    return [{"summary": str((data or {}).get("summary", "")), "exam_density": "high"}]
"""

NOTED = """  - name: ask
    kind: tool
    dependencies: [flatten]
    intent: "Tag"
    schema: tool_action_output
    impl: note_and_tag
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""

# Added to the tool, it edits it without turning any record away.
PASSING_GUARD = """    guard:
      condition: "flatten.summary != 'never'"
      on_false: filter
"""


def _config(root):
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _run():
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW])


def _add(root, action):
    _config(root).write_text(_config(root).read_text().rstrip("\n") + "\n" + action)


def _strip_last_source_guid(root):
    """What an upstream file edited outside the framework leaves. Returns its target_id."""
    backend = _backend(root)
    try:
        (path,) = backend.list_target_files(ACTION)
        rows = backend._read_target_raw(ACTION, path)
        del rows[-1]["source_guid"]
        backend._write_target_raw(ACTION, path, rows)
        return rows[-1]["target_id"]
    finally:
        backend.close()


def _held(root):
    backend = _backend(root)
    try:
        return [
            row
            for path in backend.list_target_files(BELOW)
            for row in backend.read_target(BELOW, path)
        ]
    finally:
        backend.close()


def _traced_with_no_source_guid(root):
    backend = _backend(root)
    try:
        return [trace for trace in backend.get_prompt_traces(BELOW) if not trace["source_guid"]]
    finally:
        backend.close()


def _failed(root):
    return [
        (row.get("source_guid"), row.get("target_id"))
        for row in _held(root)
        if row.get("_state") == "failed"
    ]


def test_an_llm_action_neither_renders_nor_sends_a_prompt_for_such_a_record(
    project,  # noqa: F811
    monkeypatch,
):
    """It was rendered, traced and sent, and refused only once its answer came back."""
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    _add(project, ASK)
    prompt = project / "prompt_store" / "ask.md"
    prompt.write_text(ASK_PROMPT % "Ask a question about this summary.")
    first = _run()
    assert first.exit_code == 0, first.output
    nameless = _strip_last_source_guid(project)
    prompt.write_text(ASK_PROMPT % "Ask one question about this summary.")

    result = _run()

    assert result.exit_code == 0, result.output
    assert _traced_with_no_source_guid(project) == []
    assert _failed(project) == [(None, nameless)]


def test_a_record_level_tool_is_not_called_for_such_a_record(project):  # noqa: F811
    """A tool below the first stage is prepared as an LLM action is, and was called."""
    _add(project, NOTED)
    (project / "tools" / WORKFLOW / "noted.py").write_text(NOTED_TOOL)
    first = _run()
    assert first.exit_code == 0, first.output
    nameless = _strip_last_source_guid(project)
    _add(project, PASSING_GUARD)
    calls = project / "calls.jsonl"
    calls.unlink()

    result = _run()

    assert result.exit_code == 0, result.output
    assert len(calls.read_text().splitlines()) == RECORDS - 1
    assert _failed(project) == [(None, nameless)]
