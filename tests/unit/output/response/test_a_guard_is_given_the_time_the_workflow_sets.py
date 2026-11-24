"""A guard's time limit is set in the workflow: `guard: {timeout:}` or `defaults:
guard_timeout`."""

from unittest.mock import patch

import pytest

from agent_actions.config.schema import DefaultsConfig
from agent_actions.errors import ConfigurationError, ConfigValidationError
from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.input.preprocessing.filtering.guard_filter import FilterResult, GuardFilter
from agent_actions.output.response.expander import ActionExpander
from agent_actions.output.response.expander_action_types import process_guard_config


def _expanded(guard, defaults=None) -> dict:
    agent: dict = {}
    process_guard_config(agent, {"name": "a", "guard": guard}, defaults or {})
    return agent


def test_a_guard_with_timeout_30_waits_up_to_30_seconds():
    agent = _expanded({"condition": "x > 0", "on_false": "filter", "timeout": 30})
    evaluator = GuardEvaluator(GuardFilter())
    try:
        with patch.object(
            evaluator._filter,
            "filter_item",
            return_value=FilterResult(success=True, matched=True),
        ) as filter_item:
            evaluator.evaluate({"x": 1}, agent["guard"])
    finally:
        evaluator._filter.shutdown()

    assert agent["guard"]["timeout"] == 30
    (request,) = filter_item.call_args.args
    assert request.timeout == 30


def test_a_guard_with_no_timeout_waits_the_default_5_seconds():
    agent = _expanded({"condition": "x > 0"})
    evaluator = GuardEvaluator(GuardFilter())
    try:
        with patch.object(
            evaluator._filter,
            "filter_item",
            return_value=FilterResult(success=True, matched=True),
        ) as filter_item:
            evaluator.evaluate({"x": 1}, agent["guard"])
    finally:
        evaluator._filter.shutdown()

    assert "timeout" not in agent["guard"]
    assert filter_item.call_args.args[0].timeout == 5


def test_the_defaults_guard_timeout_applies_to_a_guard_that_sets_none():
    assert _expanded({"condition": "x > 0"}, {"guard_timeout": 12})["guard"]["timeout"] == 12
    assert _expanded("x > 0", {"guard_timeout": 12})["guard"]["timeout"] == 12


def test_a_guard_s_own_timeout_wins_over_the_defaults():
    agent = _expanded({"condition": "x > 0", "timeout": 30}, {"guard_timeout": 12})

    assert agent["guard"]["timeout"] == 30


def test_the_defaults_guard_timeout_reaches_the_expanded_action():
    action = {"name": "a", "intent": "i", "prompt": "p", "guard": "x > 0"}
    agent = {"agent_type": "a", "name": "a"}
    defaults = {
        "guard_timeout": 12,
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "api_key": "OPENAI_API_KEY",
    }

    expanded = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)

    assert expanded["guard"]["timeout"] == 12


@pytest.mark.parametrize("value", [0, -1, True, "30", None])
def test_a_timeout_that_is_not_a_positive_number_is_refused(value):
    with pytest.raises(ConfigValidationError, match="timeout"):
        _expanded({"condition": "x > 0", "timeout": value})


def test_a_timeout_on_a_udf_guard_is_refused():
    with pytest.raises(ConfigurationError, match="timeout"):
        _expanded({"condition": "udf:keep", "on_false": "skip", "timeout": 30})


def test_the_defaults_block_takes_a_guard_timeout_and_refuses_one_that_is_not_positive():
    assert DefaultsConfig.model_validate({"guard_timeout": 30}).guard_timeout == 30
    with pytest.raises(ValueError, match="guard_timeout"):
        DefaultsConfig.model_validate({"guard_timeout": 0})
