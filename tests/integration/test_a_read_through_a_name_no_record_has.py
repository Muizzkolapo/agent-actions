"""A prompt or guard that reads `action.<producer>.<field>`, `prompt.x` or `schema.x` is
refused by pre-flight, in either run mode (1512).

The docs read an upstream action's fields under the action's own name
(`{{ producer.field }}`) and list `action`, `prompt` and `schema` as reserved names, not
namespaces. Pre-flight read `action.producer.field` as `producer.field` and treated
`prompt` and `schema` as always present, so the run started: every record of a prompt
then failed with "'action' is undefined", and a guard filtered every record while the
run reported success.
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
    {"page_id": "p1", "page_content": "high"},
    {"page_id": "p2", "page_content": "low"},
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
description: "Read an upstream action's field"
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
  - name: producer
    kind: tool
    intent: "Produce a severity"
    schema: producer_out
    impl: produce
    context_scope: {{ observe: [source.page_content] }}
  - name: consumer
    intent: "Consume"
    dependencies: [producer]
    schema: consumer_out
    prompt: $w.Consume
    context_scope: {{ observe: [{observe}] }}
{guard}"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def produce(data: Any, *args) -> list[dict]:
    return [{"severity": data["source"]["page_content"]}]
"""

_PRODUCER_SCHEMA = """\
name: producer_out
fields:
  - id: severity
    type: string
"""

_CONSUMER_SCHEMA = """\
name: consumer_out
fields:
  - id: summary
    type: string
"""


def _project(
    tmp_path: Path,
    mode: str,
    prompt: str,
    *,
    observe: str = "producer.severity",
    guard: str = "",
    extra: str = "",
) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    guard_yaml = f'    guard: {{ condition: "{guard}", on_false: filter }}\n' if guard else ""
    guard_yaml += extra
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _WORKFLOW.format(mode=mode, observe=observe, guard=guard_yaml)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(
        "# w - prompt store\n\n{prompt Consume}\n" + prompt + "\n{end_prompt}\n"
    )
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "producer_out.yml").write_text(_PRODUCER_SCHEMA)
    (root / "schema" / WORKFLOW / "consumer_out.yml").write_text(_CONSUMER_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "produce.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run(project: Path, *extra: str):
    return run_agac(
        project,
        "run",
        "-a",
        WORKFLOW,
        *extra,
        env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )


def _run_to_the_end(project: Path) -> str:
    outputs = []
    args: tuple[str, ...] = ("--fresh",)
    for _ in range(4):
        result = _run(project, *args)
        output = result.stdout + result.stderr
        outputs.append(output)
        assert result.returncode == 0, "\n".join(outputs)
        if "run again" not in output:
            return "\n".join(outputs)
        args = ()
    pytest.fail("the workflow never stopped asking to be run again:\n" + "\n".join(outputs))


def _store_rows(project: Path, sql: str) -> list[tuple]:
    dbs = list((project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db"))
    if not dbs:
        return []
    con = sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True)
    try:
        return list(con.execute(sql))
    finally:
        con.close()


def _consumer_dispositions(project: Path) -> list[str]:
    rows = _store_rows(
        project,
        "select disposition from record_disposition where action_name = 'consumer'",
    )
    return sorted(disposition for (disposition,) in rows)


def _assert_refused(project: Path, *expected: str) -> None:
    result = _run(project, "--fresh")
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode != 0, output
    assert "PreFlightValidationError" in output, output
    for text in expected:
        assert text in output, output
    assert _consumer_dispositions(project) == [], "the action ran"


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize(
    ("prompt", "written", "suggested"),
    [
        (
            "{{ action.producer.severity }}",
            "{{ action.producer.severity }}",
            "{{ producer.severity }}",
        ),
        (
            "{% for k, v in action.producer.items() %}{{ k }}={{ v }}{% endfor %}",
            "{{ action.producer.items() }}",
            "{{ producer.items() }}",
        ),
        (
            "{{ action.producer.get('severity') }}",
            "{{ action.producer.get('severity') }}",
            "{{ producer.get('severity') }}",
        ),
    ],
)
def test_a_prompt_reading_through_action_is_refused(tmp_path, mode, prompt, written, suggested):
    project = _project(tmp_path, mode, prompt)

    _assert_refused(project, "there is no 'action' namespace", written, f"Write '{suggested}'")


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize("prompt", ["{{ action }}", "{{ action['producer'] }}"])
def test_a_prompt_reading_action_whole_is_refused(tmp_path, mode, prompt):
    project = _project(tmp_path, mode, "{{ producer.severity }} " + prompt)

    _assert_refused(project, "there is no 'action' namespace")


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize("name", ["prompt", "schema"])
def test_a_prompt_reading_another_reserved_name_is_refused(tmp_path, mode, name):
    project = _project(tmp_path, mode, "{{ producer.severity }} {{ " + name + ".text }}")

    _assert_refused(project, f"'{name}' is a reserved name, not a namespace")


@pytest.mark.parametrize(
    ("mode", "read"),
    [
        ("online", {"guard": "action.producer.severity == 'high'"}),
        ("batch", {"guard": "action.producer.severity == 'high'"}),
        ("online", {"observe": "action.producer.severity"}),
    ],
    ids=["guard-online", "guard-batch", "context-scope"],
)
def test_a_guard_or_context_scope_reading_through_action_is_refused(tmp_path, mode, read):
    project = _project(tmp_path, mode, "{{ producer.severity }}", **read)

    _assert_refused(project, "there is no 'action' namespace", "Write 'producer.severity'")


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_the_documented_spelling_still_runs(tmp_path, mode):
    project = _project(
        tmp_path,
        mode,
        "severity={{ producer.severity }}",
        guard="producer.severity == 'high'",
    )

    _run_to_the_end(project)

    sent = trace_rows(
        project, "select compiled_prompt from prompt_trace where action_name = 'consumer'"
    )
    assert [" ".join(p.split()) for (p,) in sent] == ["severity=high"]
    assert _consumer_dispositions(project) == ["filtered", "success"]


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_version_param_named_schema_is_still_read(tmp_path, mode):
    """`versions: {param: schema}` puts `schema` on the record, so `{{ schema }}` renders."""
    project = _project(
        tmp_path,
        mode,
        "round={{ schema }} severity={{ producer.severity }}",
        extra="    versions: { param: schema, range: [1, 2] }\n",
    )

    _run_to_the_end(project)

    sent = trace_rows(
        project, "select compiled_prompt from prompt_trace where action_name like 'consumer_%'"
    )
    assert sorted(" ".join(text.split()) for (text,) in sent) == [
        "round=1 severity=high",
        "round=1 severity=low",
        "round=2 severity=high",
        "round=2 severity=low",
    ]
