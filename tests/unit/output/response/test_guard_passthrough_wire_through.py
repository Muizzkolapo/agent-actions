"""passthrough_on_error must reach the runtime guard dict for SQL guards and
change evaluator behavior on an evaluation error."""

from __future__ import annotations

from unittest.mock import patch

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.output.response.expander_action_types import process_guard_config


def test_expander_forwards_passthrough_on_error_for_sql_guard():
    agent: dict = {}
    action = {
        "name": "a",
        "guard": {"condition": "x > 0", "on_false": "filter", "passthrough_on_error": False},
    }
    process_guard_config(agent, action)
    assert agent["guard"]["passthrough_on_error"] is False


def test_expander_defaults_passthrough_on_error_true():
    agent: dict = {}
    action = {"name": "a", "guard": {"condition": "x > 0", "on_false": "filter"}}
    process_guard_config(agent, action)
    assert agent["guard"]["passthrough_on_error"] is True


def test_evaluator_applies_behavior_when_passthrough_on_error_false():
    evaluator = GuardEvaluator()
    guard = {
        "clause": "x > 0",
        "scope": "item",
        "behavior": "filter",
        "passthrough_on_error": False,
    }
    with patch.object(evaluator, "_filter") as mock_filter:
        mock_filter.filter_item.side_effect = TypeError("boom")
        result = evaluator.evaluate({"x": 1}, guard)
    assert result.should_execute is False
    assert result.behavior == "filter"


def test_evaluator_passes_record_when_passthrough_on_error_true():
    evaluator = GuardEvaluator()
    guard = {"clause": "x > 0", "scope": "item", "behavior": "filter", "passthrough_on_error": True}
    with patch.object(evaluator, "_filter") as mock_filter:
        mock_filter.filter_item.side_effect = TypeError("boom")
        result = evaluator.evaluate({"x": 1}, guard)
    assert result.should_execute is True
