"""Every action's prompt and guard read the run's `workflow.*`, and a versioned one its
`version.*`, in either run mode.

Each run is its own `agac run` process against the agac provider mock. What a prompt
rendered is read back from the action's prompt traces, which also say which run wrote
them.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "wfmeta"
PAGES = 3

_HEAD = """\
name: wfmeta
description: "Workflow metadata in prompts and guards"
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

_FIRST = """\
  - name: summarize
    intent: "Summarise"
    schema: wfmeta_summary
    prompt: $wfmeta.{prompt}
    context_scope: {{ observe: [source.page_content] }}
"""

_VERSIONED_FIRST = """\
  - name: summarize
    intent: "Summarise"
    schema: wfmeta_summary
    versions: {{ param: voter_id, range: [1, 2] }}
    prompt: $wfmeta.{prompt}
    context_scope: {{ observe: [source.page_content] }}
"""

_BELOW = """\
  - name: ask
    dependencies: [summarize]
    intent: "Ask"
    schema: wfmeta_summary
    prompt: $wfmeta.{prompt}
    context_scope: {{ observe: [summarize.summary] }}
"""

# Fails the page the project's `fail_page` names, standing in for any record-level fault.
_FLAKY_FIRST = """\
  - name: summarize
    kind: tool
    intent: "Summarise"
    schema: wfmeta_summary
    impl: summarize_unless_marked
    context_scope: { observe: [source.page_id, source.page_content] }
"""

_FLAKY_TOOL = """\
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def summarize_unless_marked(data: Any, *args) -> list[dict]:
    page = data["source"]
    marker = Path("fail_page")
    if marker.exists() and page["page_id"] == marker.read_text().strip():
        raise RuntimeError(f"tool fault on {page['page_id']}")
    return [{"summary": page["page_content"], "exam_density": "low"}]
"""

_WORKFLOW_GUARD = '    guard: { condition: "workflow.name == \\"wfmeta\\"", on_false: filter }\n'

# The workflow config is rendered before it is read, so `workflow.*` and `version.*`
# have to sit in the prompt store, where they are left for the prompt's own rendering.
_PROMPTS = """\
{prompt Plain}
Summarise this page: {{ source.page_content }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}

{prompt WorkflowFirst}
For {{ workflow.name }} run {{ workflow.run_id }}, summarise: {{ source.page_content }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}

{prompt VersionFirst}
Voter {{ version.i }} of {{ version.length }} summarises: {{ source.page_content }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}

{prompt PlainBelow}
Restate this summary: {{ summarize.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}

{prompt WorkflowBelow}
For {{ workflow.name }} run {{ workflow.run_id }}, restate: {{ summarize.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

_SCHEMA = """\
name: wfmeta_summary
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""

MODES = ["online", "batch"]


def _project(tmp_path: Path, config: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(PAGES)])
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "wfmeta_summary.yml").write_text(_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
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
            "-u",
            "tools",
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


def _traces(project: Path, action: str) -> list[tuple[str, str | None]]:
    """The action's first-attempt prompts, with the run each was written by."""
    return _query(
        project,
        "select compiled_prompt, run_id from prompt_trace where action_name = ? and attempt = 0",
        action,
    )


def _states(project: Path, action: str) -> list[str]:
    states = []
    for (blob,) in _query(project, "select data from target_data where action_name = ?", action):
        loaded = json.loads(blob)
        states += [row.get("_state") for row in (loaded if isinstance(loaded, list) else [loaded])]
    return sorted(states)


def _assert_rendered_workflow(project: Path, action: str) -> None:
    traces = _traces(project, action)
    assert len(traces) == PAGES, traces
    for prompt, run_id in traces:
        assert run_id, f"{action}'s trace names no run: {prompt!r}"
        assert f"For wfmeta run {run_id}," in prompt, prompt


# ── an action below the first stage ──────────────────────────────────────


@pytest.mark.parametrize("mode", MODES)
def test_a_prompt_below_the_first_action_reads_the_workflow(tmp_path, mode):
    config = (
        _HEAD.format(mode=mode)
        + _FIRST.format(prompt="Plain")
        + _BELOW.format(prompt="WorkflowBelow")
    )
    project = _project(tmp_path, config)

    _run_to_the_end(project)

    _assert_rendered_workflow(project, "ask")
    assert _states(project, "ask") == ["processed"] * PAGES


@pytest.mark.parametrize("mode", MODES)
def test_a_guard_below_the_first_action_reads_the_workflow(tmp_path, mode):
    """Unread, the guard cannot be evaluated: every record is filtered and the run
    still exits 0 with the action skipped."""
    below = _BELOW.format(prompt="PlainBelow") + _WORKFLOW_GUARD
    project = _project(tmp_path, _HEAD.format(mode=mode) + _FIRST.format(prompt="Plain") + below)

    _run_to_the_end(project)

    assert _states(project, "ask") == ["processed"] * PAGES


def test_traces_below_the_first_action_name_the_run(tmp_path):
    config = (
        _HEAD.format(mode="online")
        + _FIRST.format(prompt="Plain")
        + _BELOW.format(prompt="PlainBelow")
    )
    project = _project(tmp_path, config)

    _run_to_the_end(project)

    (run_id,) = {run_id for _, run_id in _traces(project, "summarize")}
    assert run_id
    assert [run for _, run in _traces(project, "ask")] == [run_id] * PAGES


def test_a_retry_below_the_first_action_reads_the_retrys_workflow(tmp_path):
    """`agac retry` re-runs a record the action above failed, and the action below
    renders and guards it with the retry's own run."""
    below = _BELOW.format(prompt="WorkflowBelow") + _WORKFLOW_GUARD
    project = _project(tmp_path, _HEAD.format(mode="online") + _FLAKY_FIRST + below)
    (project / "tools" / WORKFLOW).mkdir()
    (project / "tools" / WORKFLOW / "flaky.py").write_text(_FLAKY_TOOL)
    marker = project / "fail_page"
    marker.write_text("p1")
    _run_to_the_end(project)
    (first_run,) = {run_id for _, run_id in _traces(project, "summarize")}
    marker.unlink()

    result = run_agac(project, "retry", "-a", WORKFLOW)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _states(project, "ask") == ["processed"] * PAGES
    _assert_rendered_workflow(project, "ask")
    retried = [run_id for _, run_id in _traces(project, "ask") if run_id != first_run]
    assert len(retried) == 1, _traces(project, "ask")


# ── the first action ─────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", MODES)
def test_a_first_action_prompt_reads_the_workflow(tmp_path, mode):
    project = _project(tmp_path, _HEAD.format(mode=mode) + _FIRST.format(prompt="WorkflowFirst"))

    _run_to_the_end(project)

    _assert_rendered_workflow(project, "summarize")
    assert _states(project, "summarize") == ["processed"] * PAGES


@pytest.mark.parametrize("mode", MODES)
def test_a_versioned_first_action_prompt_reads_its_version(tmp_path, mode):
    project = _project(
        tmp_path, _HEAD.format(mode=mode) + _VERSIONED_FIRST.format(prompt="VersionFirst")
    )

    _run_to_the_end(project)

    for i in (1, 2):
        prompts = [prompt for prompt, _ in _traces(project, f"summarize_{i}")]
        assert len(prompts) == PAGES, prompts
        assert all(f"Voter {i} of 2 summarises" in prompt for prompt in prompts), prompts
        assert _states(project, f"summarize_{i}") == ["processed"] * PAGES


@pytest.mark.parametrize("mode", MODES)
def test_a_versioned_first_action_guard_reads_its_version(tmp_path, mode):
    """Unread, every record of both versions is filtered and the run exits 0."""
    first = _VERSIONED_FIRST.format(prompt="Plain") + (
        '    guard: { condition: "version.i == 1", on_false: filter }\n'
    )
    project = _project(tmp_path, _HEAD.format(mode=mode) + first)

    _run_to_the_end(project)

    assert _states(project, "summarize_1") == ["processed"] * PAGES
    assert _traces(project, "summarize_2") == []
