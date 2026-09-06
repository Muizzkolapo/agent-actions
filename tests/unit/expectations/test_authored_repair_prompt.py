"""`repair: {prompt: ...}` — the failure payload, in the author's own words."""

from __future__ import annotations

import pytest

from agent_actions.expectations.service import (
    ExpectationService,
    create_expectation_service_from_config,
)
from agent_actions.expectations.types import Expectation, Suite

SCHEMA = {
    "name": "act",
    "fields": [
        {"name": "title", "type": "string", "required": True},
        {"name": "score", "type": "integer", "required": True},
    ],
}
RULE = Expectation(id="title_set", type="not_null", field="title", hint="give it a title")
SUITE = Suite(name="s", expectations=[RULE])

RULE_FAIL = {"title": "", "score": 1}
SCHEMA_FAIL = {"title": "ok"}
GOOD = {"title": "ok", "score": 1}
ORIGINAL = "ORIGINAL TASK"

TEMPLATE = "{original_prompt}\n>> FIX THESE <<\n{failed_lines}\n>> KEEP <<\n{passing_lines}"


def service(**kwargs) -> ExpectationService:
    return ExpectationService(SUITE, schema=SCHEMA, max_iterations=3, **kwargs)


def run(svc, responses):
    prompts: list[str] = []
    remaining = list(responses)

    def generate(prompt):
        prompts.append(prompt)
        return remaining.pop(0), True

    svc.execute(generate, ORIGINAL)
    return prompts


def test_the_authored_template_becomes_the_regeneration_prompt():
    prompts = run(service(repair={"prompt": TEMPLATE}), [RULE_FAIL, GOOD])

    assert prompts[0] == ORIGINAL
    assert ">> FIX THESE <<" in prompts[1]


def test_it_receives_the_same_failure_payload_auto_composes():
    prompts = run(service(repair={"prompt": TEMPLATE}), [RULE_FAIL, GOOD])

    assert ORIGINAL in prompts[1]
    assert "title_set" in prompts[1]
    assert "give it a title" in prompts[1], "the rule's hint travels with it"


def test_the_authored_wording_replaces_the_built_in_wording():
    prompts = run(service(repair={"prompt": TEMPLATE}), [RULE_FAIL, GOOD])

    assert "Your previous output failed validation" not in prompts[1]


def test_a_template_may_use_only_the_placeholders_it_wants():
    prompts = run(service(repair={"prompt": "Redo it. {failed_lines}"}), [RULE_FAIL, GOOD])

    assert prompts[1].startswith("Redo it.")
    assert "title_set" in prompts[1]


def test_the_previous_output_is_available_to_the_template():
    prompts = run(service(repair={"prompt": "was: {response_json}"}), [RULE_FAIL, GOOD])

    assert '"title"' in prompts[1]


def test_an_unknown_placeholder_is_refused_with_the_known_ones_named():
    with pytest.raises(ValueError, match="failed_lines"):
        service(repair={"prompt": "fix {whatever}"})


def test_a_non_string_prompt_is_refused():
    with pytest.raises(ValueError, match="prompt"):
        service(repair={"prompt": 42})


def test_a_mapping_with_the_wrong_key_is_refused():
    with pytest.raises(ValueError, match="prompt"):
        service(repair={"template": TEMPLATE})


def test_structural_takes_an_authored_template_too():
    prompts = run(
        service(repair="auto", structural={"prompt": "SCHEMA BROKE: {failed_lines}"}),
        [SCHEMA_FAIL, GOOD],
    )

    assert prompts[1].startswith("SCHEMA BROKE:")
    assert "_structural" in prompts[1]


def test_each_key_governs_its_own_failure_kind():
    prompts = run(
        service(repair={"prompt": "RULES: {failed_lines}"}, structural="retry"),
        [SCHEMA_FAIL, RULE_FAIL, GOOD],
    )

    assert prompts[1] == ORIGINAL, "schema failure re-rolls"
    assert prompts[2].startswith("RULES:"), "rule failure uses the authored template"


def test_an_authored_structural_template_is_refused_under_repair_none():
    with pytest.raises(ValueError, match="repair: none"):
        service(repair="none", structural={"prompt": TEMPLATE})


class TestFromConfig:
    @staticmethod
    def build(expect):
        return create_expectation_service_from_config(
            expect, action_name="act", agent_config={"name": "act", "schema": SCHEMA}
        )

    def test_the_mapping_form_is_no_longer_refused(self):
        assert self.build({"repair": {"prompt": TEMPLATE}}).repair == {"prompt": TEMPLATE}

    def test_an_unknown_placeholder_is_refused_at_config(self):
        with pytest.raises(Exception, match="failed_lines"):
            self.build({"repair": {"prompt": "fix {whatever}"}})


def _preflight(expect):
    from pathlib import Path

    from agent_actions.validation.expectations_validator import find_expectation_defects

    return find_expectation_defects(
        {"act": {"expect": expect, "schema": SCHEMA}},
        {"act": {"title", "score"}},
        project_root=Path("."),
    ).get("act", [])


def test_preflight_accepts_a_valid_authored_template():
    assert _preflight({"repair": {"prompt": TEMPLATE}}) == []


def test_preflight_refuses_an_unknown_placeholder():
    assert any("whatever" in d for d in _preflight({"repair": {"prompt": "fix {whatever}"}}))


def test_preflight_no_longer_says_the_form_is_unimplemented():
    defects = _preflight({"repair": {"prompt": TEMPLATE}})
    assert not any("not implemented" in d for d in defects)
