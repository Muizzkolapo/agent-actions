"""`agac run` lints the prompt files its load read, wherever they are, and no others."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.trace_store import trace_rows

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: gpt-oss:120b-cloud
tool_path: ["tools"]
schema_path: schema
seed_data_path: seed_data
"""

_HEAD = """\
name: w
description: "Prompts from several prompt folders"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
"""

_ACTION = """\
  - name: {name}
    intent: "Analyze the page"
    prompt: {prompt}
    schema: {{answer: string}}
    context_scope: {{ observe: [source.title] }}
"""


def _empty_block(prompt_id: str, file_name: str) -> str:
    return f"Empty prompt content for ID '{prompt_id}' in file '{file_name}'."


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _run(root: Path, actions: dict[str, str]) -> tuple[int, str]:
    workflow = root / "agent_workflow" / "w"
    config = _HEAD + "".join(_ACTION.format(name=n, prompt=p) for n, p in actions.items())
    _write(workflow / "agent_config" / "w.yml", config)
    _write(
        workflow / "agent_io" / "staging" / "pages.json",
        json.dumps([{"title": "Alpha", "page_content": "x"}]),
    )
    for folder in ("prompt_store", "schema", "seed_data", "tools"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    _write(root / "agent_actions.yml", _PROJECT)
    _write(root / ".env", "OLLAMA_API_KEY=not-used\n")
    result = run_agac(root, "run", "-a", "w", "--fresh")
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def _prompts(root: Path) -> list[str]:
    rows = trace_rows(root, "select action_name, compiled_prompt from prompt_trace")
    return sorted(f"{action}: {prompt}" for action, prompt in rows)


@pytest.fixture(scope="module")
def loaded(tmp_path_factory) -> tuple[Path, int, str]:
    """A clean `w.md`, and malformed files the run loads from a workflow folder, a subfolder
    of one, and a nested `load_prompt` tag."""
    root = tmp_path_factory.mktemp("loaded") / "project"
    store = root / "prompt_store"
    workflow_store = root / "agent_workflow" / "w" / "prompt_store"
    _write(store / "w.md", "# W\n\n{prompt Clean}\nHello.\n{end_prompt}\n")
    _write(
        workflow_store / "wf_prompts.md",
        "# Prompts\n\n{prompt Good}\nReview {{ source.title }}.\n{end_prompt}\n\n"
        "{prompt WfEmpty}\n{end_prompt}\n",
    )
    _write(
        workflow_store / "sub" / "deep.md",
        "# Deep\n\n{prompt Deep}\nDeep {{ source.title }}.\n{end_prompt}\n\n"
        "{prompt DeepEmpty}\n{end_prompt}\n",
    )
    _write(
        store / "outer.md",
        '# Outer\n\n{prompt Main}\n{{ load_prompt("inner.Header") }}\n{end_prompt}\n',
    )
    _write(
        store / "sub" / "inner.md",
        "# Inner\n\n{prompt Header}\nInner {{ source.title }}.\n{end_prompt}\n\n"
        "{prompt InnerEmpty}\n{end_prompt}\n",
    )
    code, output = _run(
        root, {"wf": "$wf_prompts.Good", "deep": "$deep.Deep", "nested": "$outer.Main"}
    )
    return root, code, output


@pytest.fixture(scope="module")
def unreferenced(tmp_path_factory) -> tuple[int, str]:
    """No `w.md`; a referenced malformed file, an unreferenced one, and an unreferenced
    file name that is in two places."""
    root = tmp_path_factory.mktemp("unreferenced") / "project"
    store = root / "prompt_store"
    _write(
        store / "used.md",
        "# Used\n\n{prompt Good}\nUse {{ source.title }}.\n{end_prompt}\n\n"
        "{prompt UsedEmpty}\n{end_prompt}\n",
    )
    _write(store / "archive" / "unused.md", "# Unused\n\n{prompt UnusedEmpty}\n{end_prompt}\n")
    _write(store / "notes.md", "# Notes\n\n{prompt Note}\nA note.\n{end_prompt}\n")
    _write(store / "archive" / "notes.md", "# Notes\n\n{prompt Note}\nA note.\n{end_prompt}\n")
    return _run(root, {"used": "$used.Good"})


def test_the_run_loads_each_prompt(loaded):
    root, code, output = loaded

    assert code == 0, output
    assert _prompts(root) == [
        "deep: Deep Alpha.",
        "nested: Inner Alpha.",
        "wf: Review Alpha.",
    ]


def test_a_clean_workflow_named_file_does_not_hide_a_loaded_workflow_folder_file(loaded):
    _, code, output = loaded

    assert code == 0, output
    assert _empty_block("WfEmpty", "wf_prompts.md") in output, output


def test_the_lint_reports_a_loaded_file_in_a_workflow_folder_subfolder(loaded):
    _, code, output = loaded

    assert code == 0, output
    assert _empty_block("DeepEmpty", "deep.md") in output, output


def test_the_lint_reports_a_file_loaded_only_by_a_nested_load_prompt_tag(loaded):
    _, code, output = loaded

    assert code == 0, output
    assert _empty_block("InnerEmpty", "inner.md") in output, output


def test_the_lint_reports_a_referenced_file_and_not_an_unreferenced_one(unreferenced):
    code, output = unreferenced

    assert code == 0, output
    assert _empty_block("UsedEmpty", "used.md") in output, output
    assert "UnusedEmpty" not in output, output


def test_an_unreferenced_file_name_in_two_places_is_not_reported(unreferenced):
    code, output = unreferenced

    assert code == 0, output
    assert _empty_block("UsedEmpty", "used.md") in output, output
    assert "notes.md" not in output, output
