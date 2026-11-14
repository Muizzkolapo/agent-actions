"""`agac run` lints each prompt file its load read once, also when the load then fails."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

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
description: "Prompt files the load reads"
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
    schema: {schema}
    context_scope: {{ observe: [source.title] }}
"""


def _empty_block(prompt_id: str, file_name: str) -> str:
    return f"Empty prompt content for ID '{prompt_id}' in file '{file_name}'."


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _run(root: Path, actions: list[tuple[str, str, str]]) -> tuple[int, str]:
    workflow = root / "agent_workflow" / "w"
    config = _HEAD + "".join(
        _ACTION.format(name=name, prompt=prompt, schema=schema) for name, prompt, schema in actions
    )
    _write(workflow / "agent_config" / "w.yml", config)
    _write(workflow / "agent_io" / "staging" / "pages.json", json.dumps([{"title": "Alpha"}]))
    for folder in ("prompt_store", "schema", "seed_data", "tools"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    _write(root / "agent_actions.yml", _PROJECT)
    _write(root / ".env", "OLLAMA_API_KEY=not-used\n")
    result = run_agac(root, "run", "-a", "w", "--fresh")
    return result.returncode, " ".join((result.stdout + result.stderr).split())


@pytest.fixture(scope="module")
def failed_load(tmp_path_factory) -> tuple[int, str]:
    """The load reads `w.md`, then fails on a schema that does not exist."""
    root = tmp_path_factory.mktemp("failed") / "project"
    _write(
        root / "prompt_store" / "w.md",
        "# W\n\n{prompt Good}\nReview {{ source.title }}.\n{end_prompt}\n\n"
        "{prompt Empty}\n{end_prompt}\n",
    )
    return _run(root, [("analyze", "$w.Good", "nonexistent_schema")])


@pytest.fixture(scope="module")
def loaded(tmp_path_factory) -> tuple[int, str]:
    """An unreferenced malformed `w.md`, two loaded files that share an ID, and one file
    loaded under two names."""
    root = tmp_path_factory.mktemp("loaded") / "project"
    store = root / "prompt_store"
    _write(store / "w.md", "# W\n\n{prompt WEmpty}\n{end_prompt}\n")
    _write(
        store / "a.md",
        "# A\n\n{prompt Main}\nA {{ source.title }}.\n{end_prompt}\n\n"
        "{prompt AEmpty}\n{end_prompt}\n",
    )
    _write(store / "b.md", "# B\n\n{prompt Main}\nB {{ source.title }}.\n{end_prompt}\n")
    _write(
        store / "real.md",
        "# Real\n\n{prompt Real}\nReal {{ source.title }}.\n{end_prompt}\n\n"
        "{prompt RealEmpty}\n{end_prompt}\n",
    )
    (store / "alias.md").symlink_to(store / "real.md")
    schema = "{answer: string}"
    return _run(
        root,
        [
            ("a", "$a.Main", schema),
            ("b", "$b.Main", schema),
            ("real", "$real.Real", schema),
            ("alias", "$alias.Real", schema),
        ],
    )


def test_a_failed_load_still_lints_the_files_it_read_and_keeps_its_error(failed_load):
    code, output = failed_load

    assert code == 1, output
    assert "StaticTypeError: Action 'analyze' names schema 'nonexistent_schema'" in output
    assert _empty_block("Empty", "w.md") in output, output
    assert output.index(_empty_block("Empty", "w.md")) < output.index("Error: Configuration")


def test_an_unreferenced_workflow_named_file_is_not_linted(loaded):
    code, output = loaded

    assert code == 0, output
    assert _empty_block("AEmpty", "a.md") in output, output
    assert "WEmpty" not in output, output


def test_an_id_in_two_loaded_files_is_not_reported(loaded):
    code, output = loaded

    assert code == 0, output
    assert _empty_block("AEmpty", "a.md") in output, output
    assert "duplicate IDs" not in output, output


def test_a_file_loaded_under_two_names_is_reported_once(loaded):
    code, output = loaded

    assert code == 0, output
    assert output.count("Empty prompt content for ID 'RealEmpty'") == 1, output


def test_a_file_whose_key_is_missing_is_still_linted_before_the_load_error(tmp_path):
    root = tmp_path / "project"
    _write(
        root / "prompt_store" / "w.md",
        "# W\n\n{prompt Good}\nReview {{ source.title }}.\n{end_prompt}\n\n"
        "{prompt Empty}\n{end_prompt}\n",
    )

    code, output = _run(root, [("analyze", "$w.Typo", "{answer: string}")])

    assert code == 1, output
    assert "Typo" in output[output.index("Error:") :], output
    assert _empty_block("Empty", "w.md") in output, output
    assert output.index(_empty_block("Empty", "w.md")) < output.index("Error:")
