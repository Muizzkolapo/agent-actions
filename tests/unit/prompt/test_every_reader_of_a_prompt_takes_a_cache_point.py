"""Whatever reads a prompt template reads one with a `{% cache_point %}` as it reads the same
template without it."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

import agent_actions
from agent_actions.input.preprocessing.staging.field_validation import (
    _source_fields_every_render_reads,
)
from agent_actions.prompt.cache_scope import record_reads_in_prompt
from agent_actions.prompt.context.scope_parsing import extract_action_names_from_template
from agent_actions.prompt.handler import PromptLoader, _refuse_unexpanded_load_prompt
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.validation.prompt_ast import PromptASTAnalyzer, scan_prompt_fields_ast
from agent_actions.validation.prompt_required_field_validator import _unguarded_refs
from agent_actions.validation.static_analyzer.reference_extractor import ReferenceExtractor
from agent_actions.validation.static_analyzer.workflow_static_analyzer import analyze_workflow

WITH_POINT = "## PAGE\n{{ source.page_content }}\n{% cache_point %}\n## SLOT\n{{ slots.fact }}\n"
WITHOUT_POINT = WITH_POINT.replace("{% cache_point %}\n", "")


def _references(prompt: str) -> list[tuple[str, str]]:
    config = {"name": "write", "prompt": prompt, "context_scope": {}}
    found = ReferenceExtractor().extract_from_agent(config)
    return sorted((r.source_agent, r.field_path) for r in found)


READERS = {
    "staged source reads": _source_fields_every_render_reads,
    "prompt variables": lambda prompt: PromptASTAnalyzer().extract_variables(prompt),
    "prompt fields": scan_prompt_fields_ast,
    "unguarded references": lambda prompt: _unguarded_refs(prompt, {}),
    "upstream actions": extract_action_names_from_template,
    "field references": _references,
    "record reads": lambda prompt: record_reads_in_prompt({"prompt": prompt}),
}


@pytest.mark.parametrize("reader", READERS.values(), ids=READERS.keys())
def test_a_reader_finds_what_it_finds_without_the_tag(reader):
    found = reader(WITH_POINT)

    assert found
    assert found == reader(WITHOUT_POINT)


def test_the_prompt_syntax_check_passes_a_prompt_with_the_tag():
    assert PromptASTAnalyzer().validate_template_syntax(WITH_POINT) == (True, None)


def test_the_load_prompt_check_reads_a_prompt_with_the_tag():
    _refuse_unexpanded_load_prompt("page", WITH_POINT)
    with pytest.raises(ValueError, match="calls load_prompt"):
        _refuse_unexpanded_load_prompt("page", WITH_POINT + "{{ load_prompt(name) }}")


def test_the_static_analysis_finds_nothing_wrong_with_the_tag():
    slots = {
        "name": "slots",
        "prompt": "List {{ source.page_content }}.",
        "context_scope": {"observe": ["source.page_content"]},
        "schema": {"fact": "string"},
    }
    write = {
        "name": "write",
        "dependencies": ["slots"],
        "model_vendor": "anthropic",
        "enable_prompt_caching": True,
        "prompt": WITH_POINT,
        "context_scope": {"observe": ["source.page_content", "slots.fact"]},
        "schema": {"answer": "string"},
    }

    marked = analyze_workflow({"name": "pages", "actions": [slots, write]})
    plain = analyze_workflow(
        {"name": "pages", "actions": [slots, {**write, "prompt": WITHOUT_POINT}]}
    )

    assert marked.errors == plain.errors == []
    assert [w.message for w in marked.warnings if "cache" in w.message] == []


def test_every_jinja_environment_of_the_package_takes_the_prompt_extensions():
    bare = []
    for path in Path(agent_actions.__file__).parent.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "jinja" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("Environment", "DictKeyFirstEnvironment") and not any(
                keyword.arg == "extensions" for keyword in node.keywords
            ):
                bare.append(f"{path.name}:{node.lineno}")

    assert bare == []


# ── the workflow load ────────────────────────────────────────────────────


def _load(tmp_path: Path, workflow: str) -> dict[str, dict]:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return {action["name"]: action for action in yaml.safe_load(rendered)["actions"]}


def _prepare(action: dict, **field_context: dict) -> object:
    config = {**action, "context_scope": {"observe": ["source.page_content", "slots.fact"]}}
    return PromptPreparationService.prepare_prompt_with_field_context(
        config, action["name"], {}, field_context=field_context
    )


def test_a_prompt_kept_for_the_record_keeps_its_tag_through_the_load(tmp_path):
    actions = _load(
        tmp_path,
        """\
{% set house = "Rules of the house." %}
actions:
  - name: write
    prompt: |
      {{ house }}
      {{ source.page_content }}
      {% cache_point %}
      {{ slots.fact }}
    intent: "Write"
""",
    )

    assert "{% cache_point %}" in actions["write"]["prompt"]
    prepared = _prepare(
        actions["write"], source={"page_content": "The page."}, slots={"fact": "It rained."}
    )
    assert prepared.formatted_prompt == "Rules of the house.\nThe page.\nIt rained.\n"
    assert prepared.cache_points == (len("Rules of the house.\nThe page.\n"),)


def test_a_prompt_the_load_renders_keeps_its_tag_for_the_record(tmp_path):
    actions = _load(
        tmp_path,
        """\
{% set house = "Rules of the house." %}
actions:
  - name: write
    prompt: |
      {{ house }}
      {% cache_point %}
      Answer in one line.
    intent: "Write"
""",
    )

    assert actions["write"]["prompt"] == (
        "Rules of the house.\n{% cache_point %}\nAnswer in one line.\n"
    )
    prepared = _prepare(
        actions["write"], source={"page_content": "The page."}, slots={"fact": "It rained."}
    )
    assert prepared.formatted_prompt == "Rules of the house.\nAnswer in one line.\n"
    assert prepared.cache_points == (len("Rules of the house.\n"),)


def test_a_load_with_the_tag_gives_the_prompt_text_a_load_without_it_gives(tmp_path):
    workflow = """\
actions:
  - name: write
    prompt: |
      {{ source.page_content }}
      {% cache_point %}
      {{ slots.fact }}
    intent: "Write"
"""
    context = {"source": {"page_content": "The page."}, "slots": {"fact": "It rained."}}

    marked = _prepare(_load(tmp_path, workflow)["write"], **context)
    plain = _prepare(
        _load(tmp_path, workflow.replace("      {% cache_point %}\n", ""))["write"], **context
    )

    assert marked.formatted_prompt == plain.formatted_prompt
    assert (marked.cache_points, plain.cache_points) == ((len("The page.\n"),), ())


def test_a_prompt_store_file_with_the_tag_loads_as_written(tmp_path, monkeypatch):
    store = tmp_path / "prompt_store"
    store.mkdir()
    (store / "pages.md").write_text("{prompt Write}\n" + WITH_POINT + "{end_prompt}\n")
    (tmp_path / "agent_actions.yml").write_text("project_name: pages\n")
    monkeypatch.chdir(tmp_path)

    loaded = PromptLoader.load_prompt("pages.Write", project_root=tmp_path)

    assert loaded.strip() == WITH_POINT.strip()
