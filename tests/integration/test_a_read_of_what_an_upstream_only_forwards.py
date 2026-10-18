"""Pre-flight reads an upstream's namespace as the run stores it (1526).

An action's namespace holds what it produced, never what it observed or passed through:
a passed-through field lands under the namespace it came from. Pre-flight counted both as
the upstream's own, so a prompt reading `produce.page_content` passed and then failed every
record, and an `observe` of it passed and sent the model a null. Both are now refused, as a
guard's read was in 1516, while the field read where it really is (`source.page_id`) runs.

Also here: a first-stage guard naming its own action, which filtered every record and exited
0, is refused; and an action that does not exist is reported once, not also as an implicit
dependency.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "w"
PAGES = [
    {"page_id": "p1", "page_content": "two"},
    {"page_id": "p2", "page_content": "one"},
]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "A read of what an upstream forwards"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {mode}
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: produce
    kind: tool
    intent: "Produce"
    schema: fix1526_produce_out
    impl: fix1526_produce
    context_scope:
      observe: [source.page_content]
      passthrough: [source.page_id]
{produce_guard}  - name: consumer
    intent: "Consume"
    dependencies: [produce]
    schema: fix1526_consumer_out
    prompt: $w.consumer
    context_scope:
      observe: [{observe}]
"""

_PROMPT = """\
{{prompt consumer}}
{text}
{{end_prompt}}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def fix1526_produce(data: Any, *args) -> list[dict]:
    return [{"severity": "high"}]
"""

_PRODUCE_SCHEMA = """\
name: fix1526_produce_out
fields:
  - id: severity
    type: string
"""

_CONSUMER_SCHEMA = """\
name: fix1526_consumer_out
fields:
  - id: summary
    type: string
"""


def _project(
    tmp_path: Path,
    prompt: str = "Say {{ produce.severity }}",
    observe: str = "produce.*",
    mode: str = "online",
    produce_guard: str | None = None,
    open_schema: bool = False,
) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    guard = (
        f'    guard: {{ condition: "{produce_guard}", on_false: filter }}\n'
        if produce_guard
        else ""
    )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _WORKFLOW.format(mode=mode, observe=observe, produce_guard=guard)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPT.format(text=prompt))
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "fix1526_produce_out.yml").write_text(
        _PRODUCE_SCHEMA + ("additionalProperties: true\n" if open_schema else "")
    )
    (root / "schema" / WORKFLOW / "fix1526_consumer_out.yml").write_text(_CONSUMER_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    tool = _TOOL
    if open_schema:
        tool = tool.replace(
            '[{"severity": "high"}]',
            '[{"severity": "high", "page_content": data["source"]["page_content"]}]',
        )
    (root / "tools" / WORKFLOW / "fix1526_produce.py").write_text(tool)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> str:
    outputs = []
    args = ["run", "-a", WORKFLOW, "--fresh"]
    for _ in range(4):
        result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
        output = result.stdout + result.stderr
        outputs.append(output)
        assert result.returncode == 0, "\n".join(outputs)
        if "run again" not in output:
            return "\n".join(outputs)
        args = ["run", "-a", WORKFLOW]
    pytest.fail("the workflow never stopped asking to be run again:\n" + "\n".join(outputs))


def _dispositions(project: Path, action: str) -> list[str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition where action_name = ?", (action,)
        )
        return sorted(disposition for (disposition,) in rows)
    finally:
        con.close()


def _refused(project: Path, mode: str = "online") -> str:
    result = run_agac(
        project, "run", "-a", WORKFLOW, "--fresh", env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "PreFlightValidationError" in output, output
    store = project / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    if store.exists() and list(store.glob("*.db")):
        assert _dispositions(project, "produce") == [], output
    return output


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize("field", ["page_content", "page_id"])
def test_a_prompt_reading_a_field_the_upstream_only_forwards_is_refused(tmp_path, mode, field):
    """`produce` observes `page_content` and passes `page_id` through; it holds neither."""
    project = _project(tmp_path, prompt=f"Say {{{{ produce.{field} }}}}", mode=mode)

    output = _refused(project, mode)

    assert f"Field '{field}' not found in action 'produce' output schema" in output, output
    assert "Location: prompt" in output, output


@pytest.mark.parametrize("directive_ref", ["produce.page_content", "produce.page_id"])
def test_an_observe_of_a_field_the_upstream_only_forwards_is_refused(tmp_path, directive_ref):
    """The run sent the model `{"produce": {"page_content": null}}` for every record."""
    project = _project(tmp_path, prompt="Say hi", observe=directive_ref)

    output = _refused(project)

    field = directive_ref.split(".", 1)[1]
    assert f"Field '{field}' not found in action 'produce' output schema" in output, output


def test_a_passthrough_of_a_field_the_upstream_only_forwards_is_refused(tmp_path):
    project = _project(
        tmp_path, prompt="Say hi", observe="produce.severity]\n      passthrough: [produce.page_id"
    )

    output = _refused(project)

    assert "Field 'page_id' not found in action 'produce' output schema" in output, output
    assert "Location: context_scope.passthrough" in output, output


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize(
    ("prompt", "observe"),
    [
        ("Say hi", "produce.page_content, produce.severity"),
        ("Say {{ produce.page_content }}", "produce.*"),
    ],
)
def test_a_field_an_open_schema_admits_unlisted_still_runs(tmp_path, mode, prompt, observe):
    """`produce` observes `page_content` and also returns it; its schema admits it unlisted.

    The stored namespace holds it, so pre-flight warns that it cannot check the field
    instead of refusing it, as it does for a guard.
    """
    project = _project(tmp_path, prompt=prompt, observe=observe, mode=mode, open_schema=True)

    _run_to_the_end(project)

    assert _dispositions(project, "consumer") == ["success", "success"]
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        traces = [c for (c,) in con.execute("select llm_context from prompt_trace")]
    finally:
        con.close()
    assert any('"produce": {' in c and '"page_content": "two"' in c for c in traces), traces


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_field_read_where_it_is_stored_still_runs(tmp_path, mode):
    """The passed-through `page_id` is on the record under `source`, where it came from."""
    project = _project(
        tmp_path,
        prompt="Say {{ produce.severity }} for {{ source.page_id }}",
        observe="produce.severity, source.page_id",
        mode=mode,
    )

    _run_to_the_end(project)

    assert _dispositions(project, "consumer") == ["success", "success"]


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_first_stage_guard_naming_its_own_action_is_refused(tmp_path, mode):
    """At the first stage the record holds the staged row, never the action's own output."""
    project = _project(tmp_path, mode=mode, produce_guard="produce.severity == 'high'")

    output = _refused(project, mode)

    assert "produce: its guard names 'produce', its own action." in output, output


def test_a_first_stage_guard_on_the_staged_row_still_runs(tmp_path):
    project = _project(tmp_path, produce_guard="source.page_content == 'two'")

    _run_to_the_end(project)

    assert [d for d in _dispositions(project, "produce") if d == "success"] == ["success"]


def test_an_action_that_does_not_exist_is_reported_once(tmp_path):
    project = _project(tmp_path, prompt="Say {{ nosuch.severity }} {{ produce.severity }}")

    output = _refused(project)

    assert "Referenced action 'nosuch' does not exist in workflow" in output, output
    assert "Implicit dependency on 'nosuch'" not in output, output
