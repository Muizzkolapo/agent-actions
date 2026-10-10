"""A prompt written inline in the workflow file renders per record and per version, as a
prompt in the prompt store does, in either run mode.

Each case is a documented example driven through `agac run` against the agac provider
mock. What each record was sent is read back from the action's prompt traces.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "inline"
PAGES = [
    {"page_id": "p0", "page_content": "Photosynthesis turns light into sugar."},
    {"page_id": "p1", "page_content": "Volcanoes vent molten rock."},
]
MODES = ["online", "batch"]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: gpt-oss:120b-cloud
tool_path: ["tools"]
schema_path: schema
seed_data_path: seed_data
"""

_HEAD = """\
name: inline
description: "Inline prompts"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {mode}
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
"""

# The facts each record's upstream action gives, known in advance so the prompt below
# it can be checked against them.
_FACTS_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def facts_of(data: Any, *args) -> list[dict]:
    page = data["source"]
    return [{"facts": f"facts of {page['page_id']}"}]
"""


def _project(tmp_path: Path, mode: str, actions: str, pages: list[dict] = PAGES) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_HEAD.format(mode=mode) + actions)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(pages))
    for folder in ("templates", "schema", "seed_data", "prompt_store"):
        (root / folder).mkdir()
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "facts.py").write_text(_FACTS_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> str:
    """Run until nothing is left to collect; the whole run's output."""
    outputs = []
    args = ["--fresh"]
    for _ in range(4):
        result = run_agac(
            project,
            "run",
            "-a",
            WORKFLOW,
            *args,
            env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
        )
        output = result.stdout + result.stderr
        outputs.append(output)
        assert result.returncode == 0, "\n".join(outputs)
        if "run again" not in output:
            return "\n".join(outputs)
        args = []
    pytest.fail("the workflow never stopped asking to be run again:\n" + "\n".join(outputs))


def _query(project: Path, sql: str, *params: object) -> list[tuple]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return list(con.execute(sql, params))
    finally:
        con.close()


def _prompts(project: Path, action: str) -> list[str]:
    """What each record of the action was sent, in no particular order."""
    rows = _query(
        project,
        "select compiled_prompt from prompt_trace where action_name = ? and attempt = 0",
        action,
    )
    return sorted(prompt for (prompt,) in rows)


@pytest.mark.parametrize("mode", MODES)
def test_a_version_variable_renders_each_versions_value(tmp_path, mode):
    """versions.md "Configuration": every version was sent "strategy " with nothing after."""
    project = _project(
        tmp_path,
        mode,
        """\
  - name: extract_raw_qa
    intent: "Extract questions"
    versions:
      range: [1, 3]         # Inclusive range - creates _1, _2, _3
    prompt: |
      Extract questions using strategy {{ i }}
    schema: {answer: string}
    context_scope: { observe: [source.page_content] }
""",
    )

    _run_to_the_end(project)

    for i in (1, 2, 3):
        assert _prompts(project, f"extract_raw_qa_{i}") == [
            f"Extract questions using strategy {i}\n"
        ] * len(PAGES)


@pytest.mark.parametrize("mode", MODES)
def test_a_custom_version_param_renders_the_versions_value(tmp_path, mode):
    project = _project(
        tmp_path,
        mode,
        """\
  - name: classify
    intent: "Classify"
    versions:
      param: classifier_id
      range: [1, 2]
    prompt: "You are classifier {{ classifier_id }} (also {{ i }}, index {{ idx }}) of {{ version.length }}."
    schema: {answer: string}
    context_scope: { observe: [source.page_content] }
""",
    )

    _run_to_the_end(project)

    for i in (1, 2):
        assert _prompts(project, f"classify_{i}") == [
            f"You are classifier {i} (also {i}, index {i - 1}) of 2."
        ] * len(PAGES)


@pytest.mark.parametrize("mode", MODES)
def test_an_inline_prompt_reads_each_records_upstream_field(tmp_path, mode):
    """prompt-store.md "Inline Prompts": the workflow failed to load on the upstream name."""
    project = _project(
        tmp_path,
        mode,
        """\
  - name: extract_facts
    kind: tool
    intent: "Extract facts"
    impl: facts_of
    schema: {facts: string}
    context_scope: { observe: [source.page_id] }
  - name: simple_validate
    intent: "Validate facts"
    dependencies: [extract_facts]
    prompt: |
      Validate these facts: {{ extract_facts.facts }}
      Return: {"valid": true/false, "reason": "..."}
    schema: {valid: boolean, reason: string}
    context_scope: { observe: [extract_facts.facts] }
""",
    )

    _run_to_the_end(project)

    assert _prompts(project, "simple_validate") == [
        f"Validate these facts: facts of {page['page_id']}\n"
        'Return: {"valid": true/false, "reason": "..."}\n'
        for page in PAGES
    ]


@pytest.mark.parametrize("mode", MODES)
def test_a_branch_on_the_version_renders_per_version_and_per_record(tmp_path, mode):
    """versions.md "Multi-Strategy Extraction": a branch on `i` and a record's field."""
    project = _project(
        tmp_path,
        mode,
        """\
  - name: extract_with_strategies
    intent: "Extract"
    versions:
      range: [1, 3]
    prompt: |
      {% if i == 1 %}Focus on explicit statements
      {% elif i == 2 %}Focus on implicit meanings
      {% else %}Focus on contextual clues{% endif %}

      Extract from: {{ source.page_content }}
    schema: {answer: string}
    context_scope: { observe: [source.page_content] }
""",
    )

    _run_to_the_end(project)

    focus = {1: "explicit statements", 2: "implicit meanings", 3: "contextual clues"}
    for i, words in focus.items():
        prompts = _prompts(project, f"extract_with_strategies_{i}")
        assert len(prompts) == len(PAGES), prompts
        for prompt, page in zip(prompts, sorted(p["page_content"] for p in PAGES), strict=True):
            assert prompt.startswith(f"Focus on {words}"), prompt
            assert prompt.endswith(f"Extract from: {page}\n"), prompt


@pytest.mark.parametrize("mode", MODES)
def test_a_setting_that_branches_on_the_version_takes_each_versions_branch(tmp_path, mode):
    """versions.md "Parallel Model Comparison": every version took the else branch."""
    project = _project(
        tmp_path,
        mode,
        """\
  - name: model_comparison
    intent: "Compare models"
    versions:
      range: [1, 3]
    model_name: "{% if i == 1 %}model-one{% elif i == 2 %}model-two{% else %}model-three{% endif %}"
    prompt: "Summarise: {{ source.page_content }}"
    schema: {answer: string}
    context_scope: { observe: [source.page_content] }
""",
    )

    _run_to_the_end(project)

    for i, model in ((1, "model-one"), (2, "model-two"), (3, "model-three")):
        rows = _query(
            project,
            "select distinct model_name from prompt_trace where action_name = ?",
            f"model_comparison_{i}",
        )
        assert rows == [(model,)]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "capture, kind",
    [
        pytest.param("{% set kind %}{{ source.page_content }}{% endset %}", "kind", id="set-block"),
        pytest.param(
            "{% macro kind() %}{{ source.page_content }}{% endmacro %}", "kind()", id="macro"
        ),
    ],
)
def test_a_value_the_prompt_captures_per_record_is_tested_per_record(tmp_path, mode, capture, kind):
    """The load decided the test against the tag's text, so every record took the else."""
    pages = [
        {"page_id": "p0", "page_content": "urgent"},
        {"page_id": "p1", "page_content": "routine"},
    ]
    project = _project(
        tmp_path,
        mode,
        f"""\
  - name: triage
    intent: "Triage"
    prompt: |
      {capture}
      {{% if {kind} == "urgent" %}}ESCALATE NOW.{{% else %}}Handle normally.{{% endif %}} Kind={{{{ {kind} }}}} len={{{{ {kind} | length }}}}
    schema: {{answer: string}}
    context_scope: {{ observe: [source.page_content] }}
""",
        pages,
    )

    _run_to_the_end(project)

    assert [prompt.strip() for prompt in _prompts(project, "triage")] == [
        "ESCALATE NOW. Kind=urgent len=6",
        "Handle normally. Kind=routine len=7",
    ]
