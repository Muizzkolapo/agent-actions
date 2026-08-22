"""Observe-mode execution and service construction."""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.expectations.service import (
    ExpectationService,
    create_expectation_service_from_config,
)
from agent_actions.expectations.types import Suite

SUITE = Suite(
    name="s",
    expectations=[{"id": "count", "type": "item_count", "field": "ideas", "min": 2}],
)
INLINE = [{"type": "item_count", "field": "ideas", "min": 2}]


def passing_llm(prompt):
    return {"ideas": ["a", "b", "c"]}, True


def failing_llm(prompt):
    return {"ideas": ["a"]}, True


def test_observe_mode_calls_the_llm_exactly_once():
    calls = []

    def counting(prompt):
        calls.append(prompt)
        return {"ideas": ["a"]}, True

    ExpectationService(SUITE, repair="none").execute(counting, "PROMPT")
    assert calls == ["PROMPT"]


def test_observe_mode_returns_the_response_unchanged_when_rules_fail():
    result = ExpectationService(SUITE, repair="none").execute(failing_llm, "PROMPT")
    assert result.response == {"ideas": ["a"]}
    assert result.executed is True
    assert result.iterations == 1


def test_observe_mode_reports_the_failure_in_the_suite_result():
    result = ExpectationService(SUITE, repair="none").execute(failing_llm, "PROMPT")
    assert result.suite_result.overall_pass is False
    assert [o.id for o in result.suite_result.failed] == ["count"]


def test_observe_mode_reports_a_pass():
    result = ExpectationService(SUITE, repair="none").execute(passing_llm, "PROMPT")
    assert result.suite_result.overall_pass is True


def test_a_guard_skipped_call_is_not_validated():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: ({"x": 1}, False), "P")
    assert result.executed is False
    assert result.suite_result is None


def test_a_none_response_is_not_validated():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: (None, True), "P")
    assert result.suite_result is None


def test_a_non_dict_response_is_not_validated():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: ("text", True), "P")
    assert result.suite_result is None


def test_factory_returns_none_without_an_expect_block():
    assert create_expectation_service_from_config(None, action_name="a") is None


def test_factory_builds_an_inline_suite_named_after_the_action():
    service = create_expectation_service_from_config(
        {"expectations": INLINE, "repair": "none"}, action_name="brainstorm"
    )
    assert service.suite.name == "brainstorm:inline"


@pytest.mark.parametrize("mode", ["auto", "retry"])
def test_factory_refuses_repair_modes_this_build_does_not_implement(mode):
    with pytest.raises(ConfigurationError, match="repair: none"):
        create_expectation_service_from_config(
            {"expectations": INLINE, "repair": mode}, action_name="a"
        )


def test_factory_refuses_a_repair_prompt_mapping():
    with pytest.raises(ConfigurationError, match="repair: none"):
        create_expectation_service_from_config(
            {"expectations": INLINE, "repair": {"prompt": "$wf.Fix"}}, action_name="a"
        )
