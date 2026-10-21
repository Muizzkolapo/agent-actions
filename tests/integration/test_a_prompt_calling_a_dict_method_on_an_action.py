"""A prompt that calls a dict method on an action's namespace passes pre-flight and
renders, in either run mode (1506).

Pre-flight read `merge_alternatives.items()` as a reference to a field named `items`
and refused the run, so the prompt-store docs' "Dictionary Iteration with Filtering"
example could not run. A call such as `ns.items()` or `ns.keys()` is not a field
reference; `ns.get('field', ...)` reads that field, and a bare `ns.items` and a misspelt
field are still refused.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.trace_store import trace_rows

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
description: "Iterate over an upstream action's fields"
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
  - name: merge_alternatives
    kind: tool
    intent: "Produce alternatives"
    schema: merge_out
    impl: produce
    context_scope: {{ observe: [source.page_content] }}
  - name: consumer
    intent: "Consume"
    dependencies: [merge_alternatives]
    schema: consumer_out
    prompt: $w.Summarize_Alternatives
    context_scope: {{ observe: [merge_alternatives.*] }}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def produce(data: Any, *args) -> list[dict]:
    out = {"issue_description_1": "slow", "severity": "high"}
    if data["source"]["page_content"] == "two":
        out["issue_description_2"] = "flaky"
    return [out]
"""

_MERGE_SCHEMA = """\
name: merge_out
fields:
  - id: issue_description_1
    type: string
  - id: issue_description_2
    type: string
    required: false
  - id: severity
    type: string
"""

_CONSUMER_SCHEMA = """\
name: consumer_out
fields:
  - id: summary
    type: string
"""

# The prompt-store docs' example, verbatim, then the other calls a prompt may make.
_DOCS_PROMPT = """\
{% for key, value in merge_alternatives.items() %}
{% if 'issue_description' in key %}
- {{ value }}
{% endif %}
{% endfor %}
"""
_CALLS = (
    "second={{ merge_alternatives.get('issue_description_2', 'none') }};"
    "severity={{ merge_alternatives.get('severity') }};"
    "keys={{ merge_alternatives.keys() | sort | join(',') }};"
    "values={{ merge_alternatives.values() | list | length }}"
)


def _project(tmp_path: Path, mode: str, prompt: str) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_WORKFLOW.format(mode=mode))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(
        "# w - prompt store\n\n{prompt Summarize_Alternatives}\n" + prompt + "{end_prompt}\n"
    )
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "merge_out.yml").write_text(_MERGE_SCHEMA)
    (root / "schema" / WORKFLOW / "consumer_out.yml").write_text(_CONSUMER_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "produce.py").write_text(_TOOL)
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


def _query(project: Path, sql: str) -> list[tuple]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return list(con.execute(sql))
    finally:
        con.close()


def _sent(project: Path) -> list[str]:
    rows = trace_rows(
        project, "select compiled_prompt from prompt_trace where action_name = 'consumer'"
    )
    return sorted(" ".join(prompt.split()) for (prompt,) in rows)


def _dispositions(project: Path) -> list[str]:
    rows = _query(
        project, "select disposition from record_disposition where action_name = 'consumer'"
    )
    return sorted(disposition for (disposition,) in rows)


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_the_docs_dictionary_iteration_example_runs(tmp_path, mode):
    project = _project(tmp_path, mode, _DOCS_PROMPT)

    _run_to_the_end(project)

    assert _sent(project) == ["- slow", "- slow - flaky"]
    assert _dispositions(project) == ["success", "success"]


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_get_keys_and_values_called_on_an_action_render(tmp_path, mode):
    project = _project(tmp_path, mode, _CALLS + "\n")

    _run_to_the_end(project)

    assert _sent(project) == [
        "second=flaky;severity=high;keys=issue_description_1,issue_description_2,severity;values=3",
        "second=none;severity=high;keys=issue_description_1,severity;values=2",
    ]
    assert _dispositions(project) == ["success", "success"]


@pytest.mark.parametrize(
    ("read", "field"),
    [
        ("merge_alternatives.items", "items"),
        ("merge_alternatives.severty", "severty"),
        ("merge_alternatives.severty()", "severty"),
        ("merge_alternatives.nested.get('x')", "nested"),
        ("merge_alternatives.get('severty', 'low')", "severty"),
    ],
)
def test_a_field_the_schema_lacks_is_still_refused(tmp_path, read, field):
    project = _project(tmp_path, "online", "{{ " + read + " }}\n")

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert f"Field '{field}' not found in action 'merge_alternatives' output schema" in output, (
        output
    )
