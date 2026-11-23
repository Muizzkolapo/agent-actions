"""A judged rule's ``context:`` refs are observed, and order the actions, in every form.

The rule can sit on the action, in its own schema, or in a named suite. The load adds
its refs to ``context_scope.observe``, and dependency inference reads them there, so
the action that produces the field runs first. ``summarize`` names no dependency, and
two independent actions run in reverse declaration order: only the judged ref puts
``src`` before it.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.utils.path_utils import reset_path_manager

RULE = {
    "id": "grounded",
    "type": "llm_judge",
    "field": "summary",
    "params": {"rule": "The summary is supported by the source text.", "context": ["src.text"]},
}

FORMS = {
    "inline": {"expectations": [RULE], "repair": "none"},
    "own-schema": {"repair": "none"},
    "named-suite": {"suite": "quality", "repair": "none"},
}


def _project(root: Path, expect: dict) -> Path:
    (root / "wf" / "agent_config").mkdir(parents=True)
    (root / "wf" / "agent_io" / "staging").mkdir(parents=True)
    (root / "templates").mkdir()
    (root / "schema").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n"
        "  api_key: OPENAI_API_KEY\n"
        "  model_name: gpt-4o-mini\n"
        "  model_vendor: openai\n"
        "schema_path: schema\n"
    )
    summary_schema: dict = {"name": "summary", "fields": [{"id": "summary", "type": "string"}]}
    if "suite" not in expect and "expectations" not in expect:
        summary_schema["expectations"] = [RULE]
    (root / "schema" / "summary.yml").write_text(yaml.safe_dump(summary_schema))
    (root / "schema" / "src.yml").write_text(
        yaml.safe_dump({"name": "src", "fields": [{"id": "text", "type": "string"}]})
    )
    (root / "schema" / "quality.yml").write_text(yaml.safe_dump({"expectations": [RULE]}))
    workflow = {
        "name": "wf",
        "description": "a judged context in each form",
        "defaults": {"json_mode": True, "granularity": "Record", "run_mode": "online"},
        "actions": [
            {
                "name": "src",
                "intent": "extract",
                "prompt": "Extract {{ source.page_content }}.",
                "schema": "src",
                "context_scope": {"observe": ["source.page_content"]},
            },
            {
                "name": "summarize",
                "intent": "summarise",
                "prompt": "Summarise {{ source.page_content }}.",
                "schema": "summary",
                "context_scope": {"observe": ["source.page_content"]},
                "expect": expect,
            },
        ],
    }
    (root / "wf" / "agent_config" / "wf.yml").write_text(yaml.safe_dump(workflow, sort_keys=False))
    return root


@pytest.fixture
def load(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used")

    def _load(expect: dict) -> WorkflowInspector:
        reset_path_manager()
        try:
            inspector = WorkflowInspector("wf", project_root=_project(tmp_path / "proj", expect))
            inspector.load()
            return inspector
        finally:
            reset_path_manager()

    return _load


@pytest.mark.parametrize("expect", FORMS.values(), ids=FORMS.keys())
def test_the_judged_ref_is_observed(load, expect):
    observe = load(expect).action_configs["summarize"]["context_scope"]["observe"]

    assert "src.text" in observe


@pytest.mark.parametrize("expect", FORMS.values(), ids=FORMS.keys())
def test_the_action_that_produces_it_runs_first(load, expect):
    assert load(expect).execution_order == ["src", "summarize"]


def test_a_suite_that_does_not_load_adds_nothing_and_fails_no_load(load):
    observe = load({"suite": "missing", "repair": "none"}).action_configs["summarize"][
        "context_scope"
    ]["observe"]

    assert observe == ["source.page_content"]
