"""Pre-flight's static-analysis warnings print on their own, and each finding once (1536).

`PreflightService.validate` printed the static analyzer's warnings only inside the error
report, so `agac run` and `agac inspect` showed none of them for a workflow that passed,
such as the guard literal-type warning. A bad `context_scope.observe` entry was reported
twice, by the type checker and again by the analyzer's own context-scope check, which
measured the field against what the upstream forwards.
"""

from __future__ import annotations

import json
from pathlib import Path

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
description: "Two actions"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: produce
    kind: tool
    intent: "Produce"
    schema: fix1536_produce_out
    impl: fix1536_produce
    context_scope: {{ observe: [source.page_content] }}
  - name: consumer
    intent: "Consume"
    dependencies: [produce]
    schema: fix1536_consumer_out
    prompt: $w.consumer
    context_scope:
      observe: [{observe}]
{guard}"""

_PROMPT = """\
{prompt consumer}
Say hello
{end_prompt}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def fix1536_produce(data: Any, *args) -> list[dict]:
    return [{"severity": "high", "score": 3}]
"""

_PRODUCE_SCHEMA = """\
name: fix1536_produce_out
fields:
  - id: severity
    type: string
  - id: score
    type: integer
"""

_CONSUMER_SCHEMA = """\
name: fix1536_consumer_out
fields:
  - id: summary
    type: string
"""

_LITERAL_WARNING = "type mismatch in"


def _project(tmp_path: Path, observe: str = "produce.severity", guard: str = "") -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    guard_line = f'    guard: {{ condition: "{guard}", on_false: filter }}\n' if guard else ""
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _WORKFLOW.format(observe=observe, guard=guard_line)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPT)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "fix1536_produce_out.yml").write_text(_PRODUCE_SCHEMA)
    (root / "schema" / WORKFLOW / "fix1536_consumer_out.yml").write_text(_CONSUMER_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "fix1536_produce.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _output(result) -> str:
    return result.stdout + result.stderr


def test_agac_run_shows_a_warning_with_no_error_and_still_runs(tmp_path):
    project = _project(tmp_path, guard="produce.score == 'high'")

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = _output(result)

    assert result.returncode == 0, output
    assert output.count(_LITERAL_WARNING) == 1, output
    assert "Align the literal with the field's declared schema type." in output, output


def test_agac_inspect_shows_a_warning_with_no_error(tmp_path):
    project = _project(tmp_path, guard="produce.score == 'high'")

    result = run_agac(project, "inspect", "-a", WORKFLOW)
    output = _output(result)

    assert result.returncode == 0, output
    assert output.count(_LITERAL_WARNING) == 1, output


def test_a_workflow_with_nothing_to_warn_about_prints_no_static_warning(tmp_path):
    project = _project(tmp_path)

    result = run_agac(project, "inspect", "-a", WORKFLOW)
    output = _output(result)

    assert result.returncode == 0, output
    assert "static analysis" not in output, output


def test_a_misspelt_observe_entry_is_reported_once(tmp_path):
    project = _project(tmp_path, observe="produce.severty")

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = _output(result)

    assert result.returncode != 0, output
    assert output.count("Reference: produce.severty") == 1, output
    assert "Field 'severty' not found in action 'produce' output schema" in output, output
    assert "Total: 1 error(s)" in output, output


def test_an_observe_of_a_forwarded_field_is_reported_once_naming_where_it_is_stored(tmp_path):
    project = _project(tmp_path, observe="produce.page_content")

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = _output(result)

    assert result.returncode != 0, output
    assert output.count("Reference: produce.page_content") == 1, output
    assert "Did you mean 'source.page_content'?" in output, output
