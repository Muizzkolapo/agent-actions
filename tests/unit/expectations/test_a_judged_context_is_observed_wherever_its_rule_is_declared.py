"""A judged rule's ``context:`` refs are observed, and order the actions, in every form.

The rule can sit on the action, in its own schema, or in a named suite. The load adds
its refs to ``context_scope.observe``, and dependency inference reads them there, so
the action that produces the field runs first. ``summarize`` names no dependency, and
two independent actions run in reverse declaration order: only the judged ref puts
``src`` before it.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.utils.path_utils import reset_path_manager
from agent_actions.validation.expectations_validator import find_expectation_defects

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


def _project(
    root: Path,
    expect: dict | None,
    *,
    defaults: dict | None = None,
    src_scope: bool = True,
    sibling: bool = False,
    rule: dict = RULE,
    suite: Any = None,
    own_rules: bool = False,
    src_expect: dict | None = None,
) -> Path:
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
    if own_rules or (expect is not None and not {"suite", "expectations"} & set(expect)):
        summary_schema["expectations"] = [rule]
    (root / "schema" / "summary.yml").write_text(yaml.safe_dump(summary_schema))
    (root / "schema" / "src.yml").write_text(
        yaml.safe_dump({"name": "src", "fields": [{"id": "text", "type": "string"}]})
    )
    quality = {"expectations": [rule]} if suite is None else suite
    (root / "schema" / "quality.yml").write_text(yaml.safe_dump(quality))
    src: dict = {
        "name": "src",
        "intent": "extract",
        "prompt": "Extract {{ source.page_content }}.",
        "schema": "src",
    }
    summarize: dict = {
        "name": "summarize",
        "intent": "summarise",
        "prompt": "Summarise {{ source.page_content }}.",
        "schema": "summary",
    }
    if expect is not None:
        summarize["expect"] = expect
    if src_expect is not None:
        src["expect"] = src_expect
        src_rules = {"expectations": [{"id": "present", "type": "not_null", "field": "text"}]}
        (root / "schema" / "src_quality.yml").write_text(yaml.safe_dump(src_rules))
    if src_scope:
        src["context_scope"] = {"observe": ["source.page_content"]}
    if "context_scope" not in (defaults or {}):
        summarize["context_scope"] = {"observe": ["source.page_content"]}
    actions = [src, summarize]
    if sibling:
        actions.insert(
            1,
            {
                "name": "other",
                "intent": "other",
                "prompt": "Restate {{ source.page_content }}.",
                "schema": "summary",
            },
        )
    workflow = {
        "name": "wf",
        "description": "a judged context in each form",
        "defaults": {
            "json_mode": True,
            "granularity": "Record",
            "run_mode": "online",
            **(defaults or {}),
        },
        "actions": actions,
    }
    (root / "wf" / "agent_config" / "wf.yml").write_text(yaml.safe_dump(workflow, sort_keys=False))
    return root


@pytest.fixture
def load(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used")

    def _load(expect: dict | None, **project: Any) -> WorkflowInspector:
        reset_path_manager()
        try:
            root = _project(tmp_path / "proj", expect, **project)
            inspector = WorkflowInspector("wf", project_root=root)
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


def test_a_suite_that_does_not_load_adds_no_refs_from_the_own_schema(load):
    configs = load({"suite": "missing", "repair": "none"}, own_rules=True).action_configs

    assert configs["summarize"]["context_scope"] == {"observe": ["source.page_content"]}


def _judge(rule_id: str, *refs: str) -> dict:
    return {**RULE, "id": rule_id, "params": {**RULE["params"], "context": list(refs)}}


class TestEveryJudgedRuleOfASuiteIsRead:
    def test_two_judged_rules(self, load):
        two = {"expectations": [_judge("one", "src.text"), _judge("two", "other.summary")]}

        inspector = load({"suite": "quality", "repair": "none"}, sibling=True, suite=two)

        observe = inspector.action_configs["summarize"]["context_scope"]["observe"]
        assert observe == ["source.page_content", "src.text", "other.summary"]
        assert inspector.execution_order[-1] == "summarize"

    def test_a_judged_rule_on_a_field(self, load):
        field_rule = {k: v for k, v in RULE.items() if k != "field"}
        on_a_field = {
            "fields": [{"id": "summary", "type": "string", "expectations": [field_rule]}]
        }

        inspector = load({"suite": "quality", "repair": "none"}, suite=on_a_field)

        observe = inspector.action_configs["summarize"]["context_scope"]["observe"]
        assert observe == ["source.page_content", "src.text"]
        assert inspector.execution_order == ["src", "summarize"]


class TestASuiteFromTheDefaultsIsRead:
    def test_a_suite_under_the_workflow_defaults(self, load):
        # src names a suite of its own, so it does not judge its own field. It has no
        # scope of its own, so it inherits the defaults' scope, as summarize does.
        inherited = {"expect": {"suite": "quality", "repair": "none"}, **SHARED_SCOPE}

        inspector = load(
            None, defaults=inherited, src_scope=False, src_expect={"suite": "src_quality"}
        )

        configs = inspector.action_configs
        assert configs["summarize"]["context_scope"] == {
            "observe": ["source.page_content", "src.text"]
        }
        assert configs["src"]["context_scope"] == {"observe": ["source.page_content"]}
        assert inspector.execution_order == ["src", "summarize"]


SHARED_SCOPE = {"context_scope": {"observe": ["source.page_content"]}}
SHARING = {key: FORMS[key] for key in ("inline", "named-suite")}


class TestAScopeFromTheDefaultsIsNotShared:
    """An action with no ``context_scope`` of its own inherits the defaults' one.

    A judged ref added to it stays on the judged action: a sibling with no scope
    of its own does not observe it, and does not run after its source.
    """

    @pytest.mark.parametrize("expect", SHARING.values(), ids=SHARING.keys())
    def test_a_sibling_does_not_observe_the_judged_ref(self, load, expect):
        configs = load(expect, defaults=SHARED_SCOPE, sibling=True).action_configs

        assert configs["other"]["context_scope"] == {"observe": ["source.page_content"]}
        assert configs["summarize"]["context_scope"] == {
            "observe": ["source.page_content", "src.text"]
        }

    @pytest.mark.parametrize("expect", SHARING.values(), ids=SHARING.keys())
    def test_a_sibling_does_not_depend_on_the_source(self, load, expect):
        configs = load(expect, defaults=SHARED_SCOPE, sibling=True).action_configs

        def inferred(name: str) -> list[str]:
            inputs, context = infer_dependencies(configs[name], list(configs), name)
            return [*inputs, *context]

        assert "src" not in inferred("other")
        assert "src" in inferred("summarize")

    @pytest.mark.parametrize("expect", SHARING.values(), ids=SHARING.keys())
    def test_the_source_with_no_scope_of_its_own_loads(self, load, expect):
        inspector = load(expect, defaults=SHARED_SCOPE, src_scope=False, sibling=True)

        assert inspector.action_configs["src"]["context_scope"] == {
            "observe": ["source.page_content"]
        }
        assert inspector.execution_order.index("src") < inspector.execution_order.index(
            "summarize"
        )


NOT_NULL = {"id": "present", "type": "not_null", "field": "summary"}


def _judged_refs(inspector: WorkflowInspector, root: Path) -> list[str]:
    config = inspector.action_configs["summarize"]
    service = create_expectation_service_from_config(
        config["expect"], action_name="summarize", agent_config=config, project_root=root
    )
    assert service is not None
    return [
        ref
        for expectation in service.suite.expectations
        if expectation.type == "llm_judge"
        for ref in expectation.params.get("context") or []
    ]


class TestTheLoadObservesTheRulesTheRunJudges:
    """A defaults list under an action's suite leaves a block with both keys. The run
    judges with the suite, so the load observes the suite's refs."""

    def test_a_suite_over_an_inherited_inline_list(self, load, tmp_path):
        inspector = load(
            {"suite": "quality", "repair": "none"},
            defaults={"expect": {"expectations": [NOT_NULL]}},
        )
        config = inspector.action_configs["summarize"]

        assert {"suite", "expectations"} <= set(config["expect"])
        assert _judged_refs(inspector, tmp_path / "proj") == ["src.text"]
        assert "src.text" in config["context_scope"]["observe"]
        assert inspector.execution_order == ["src", "summarize"]


MAPPED = {**RULE, "params": {**RULE["params"], "context": [{"src": "text"}]}}
MAPPED_FORMS = {
    "inline": {"expectations": [MAPPED], "repair": "none"},
    "named-suite": {"suite": "quality", "repair": "none"},
}


class TestAMappingInContextIsLeftToPreflight:
    @pytest.mark.parametrize("expect", MAPPED_FORMS.values(), ids=MAPPED_FORMS.keys())
    def test_the_load_does_not_crash_and_preflight_names_the_rule(self, load, tmp_path, expect):
        configs = load(expect, rule=MAPPED).action_configs

        assert configs["summarize"]["context_scope"] == {"observe": ["source.page_content"]}
        defects = find_expectation_defects(
            configs,
            {"summarize": {"summary"}, "src": {"text"}},
            project_root=tmp_path / "proj",
        )
        assert defects == {
            "summarize": ["grounded: context reference '{'src': 'text'}' must be 'action.field'"]
        }
