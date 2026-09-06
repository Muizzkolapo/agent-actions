"""Re-roll or steer, chosen separately for a schema failure and a rule failure."""

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

RULE = Expectation(id="title_set", type="not_null", field="title")

CONFORMING_BUT_FAILING = {"title": "", "score": 1}
NON_CONFORMING = {"title": "ok"}
GOOD = {"title": "ok", "score": 1}

ORIGINAL = "the original rendered prompt"


def service(**kwargs) -> ExpectationService:
    return ExpectationService(
        Suite(name="s", expectations=[RULE]),
        schema=SCHEMA,
        max_iterations=3,
        **kwargs,
    )


def run(svc, responses):
    """Drive the loop over a scripted sequence, returning the prompts it issued."""
    prompts: list[str] = []
    remaining = list(responses)

    def generate(prompt):
        prompts.append(prompt)
        return remaining.pop(0), True

    svc.execute(generate, ORIGINAL)
    return prompts


def test_a_schema_failure_re_runs_the_original_prompt_by_default():
    prompts = run(service(repair="auto"), [NON_CONFORMING, GOOD])

    assert prompts == [ORIGINAL, ORIGINAL]


def test_a_rule_failure_still_steers_by_default():
    prompts = run(service(repair="auto"), [CONFORMING_BUT_FAILING, GOOD])

    assert prompts[0] == ORIGINAL
    assert prompts[1] != ORIGINAL
    assert "title_set" in prompts[1]


def test_structural_auto_steers_the_schema_failure_too():
    prompts = run(service(repair="auto", structural="auto"), [NON_CONFORMING, GOOD])

    assert prompts[1] != ORIGINAL
    assert "_structural" in prompts[1]


def test_repair_retry_re_rolls_both_kinds():
    assert run(service(repair="retry"), [NON_CONFORMING, GOOD]) == [ORIGINAL, ORIGINAL]
    assert run(service(repair="retry"), [CONFORMING_BUT_FAILING, GOOD]) == [ORIGINAL, ORIGINAL]


def test_the_two_kinds_use_their_own_prompt_within_one_loop():
    prompts = run(service(repair="auto"), [NON_CONFORMING, CONFORMING_BUT_FAILING, GOOD])

    assert prompts[0] == ORIGINAL
    assert prompts[1] == ORIGINAL, "schema failure re-rolls"
    assert "title_set" in prompts[2], "rule failure steers"


def test_both_kinds_spend_the_same_iteration_budget():
    svc = service(repair="auto")
    prompts = run(svc, [NON_CONFORMING, CONFORMING_BUT_FAILING, NON_CONFORMING])

    assert len(prompts) == 3, "max_iterations bounds the loop across both failure kinds"


def test_structural_defaults_to_retry():
    assert service(repair="auto").structural == "retry"


@pytest.mark.parametrize("mode", ["retry", "auto"])
def test_a_valid_structural_mode_is_accepted(mode):
    assert service(repair="auto", structural=mode).structural == mode


def test_an_invalid_structural_mode_is_refused():
    with pytest.raises(ValueError, match="structural"):
        service(repair="auto", structural="sideways")


def test_structural_is_meaningless_without_a_repair_policy():
    with pytest.raises(ValueError, match="repair: none"):
        service(repair="none", structural="auto")


class TestFromConfig:
    @staticmethod
    def build(expect):
        return create_expectation_service_from_config(
            expect, action_name="act", agent_config={"name": "act", "schema": SCHEMA}
        )

    def test_the_key_is_threaded_from_config(self):
        assert self.build({"repair": "auto", "structural": "auto"}).structural == "auto"

    def test_it_defaults_to_retry_from_config(self):
        assert self.build({"repair": "auto"}).structural == "retry"

    def test_an_unknown_structural_value_is_refused_at_config(self):
        with pytest.raises(Exception, match="structural"):
            self.build({"repair": "auto", "structural": "sideways"})


def _preflight(expect):
    from pathlib import Path

    from agent_actions.validation.expectations_validator import find_expectation_defects

    return find_expectation_defects(
        {"act": {"expect": expect, "schema": SCHEMA}},
        {"act": {"title", "score"}},
        project_root=Path("."),
    ).get("act", [])


def test_preflight_accepts_structural_alongside_repair():
    assert _preflight({"repair": "auto", "structural": "auto"}) == []


def test_preflight_refuses_structural_under_repair_none():
    assert any("structural" in d for d in _preflight({"repair": "none", "structural": "auto"}))
