"""passthrough_on_error must reach a UDF guard too, not just SQL guards (1315).

A UDF guard that raises for its own reason silently passed its record: the
expander refused `passthrough_on_error: false` on a UDF condition outright, so
a user who wanted the guard enforced had no way to opt out of the passthrough.
"""

from __future__ import annotations

from unittest.mock import patch

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.output.response.expander_action_types import process_guard_config
from agent_actions.utils.udf_management import registry as registry_module
from agent_actions.utils.udf_management.registry import UDF_REGISTRY


def test_expander_no_longer_refuses_passthrough_on_error_false_for_udf_guard():
    agent: dict = {}
    action = {
        "name": "a",
        "guard": {
            "condition": "udf:check_eligibility",
            "on_false": "skip",
            "passthrough_on_error": False,
        },
    }
    process_guard_config(agent, action)
    assert agent["conditional_clause"] == "check_eligibility"
    assert agent["conditional_clause_passthrough_on_error"] is False


def test_expander_defaults_udf_passthrough_on_error_true():
    agent: dict = {}
    action = {"name": "a", "guard": {"condition": "udf:check_eligibility", "on_false": "skip"}}
    process_guard_config(agent, action)
    assert agent["conditional_clause_passthrough_on_error"] is True


def test_a_bare_string_udf_guard_also_defaults_to_true():
    """`guard: "udf:name"` has no syntax for passthrough_on_error at all."""
    agent: dict = {}
    process_guard_config(agent, {"name": "a", "guard": "udf:check_eligibility"})
    assert agent["conditional_clause_passthrough_on_error"] is True


def _register(name: str, fn) -> None:
    registry_module.udf_tool(fn)


def _unregister(name: str, modules_before: set) -> None:
    UDF_REGISTRY.pop(name, None)
    registry_module._registered_modules.intersection_update(modules_before)


def test_evaluator_skips_when_udf_raises_and_passthrough_on_error_false():
    def guard_udf_that_explodes_1315(data):
        raise RuntimeError("boom")

    modules_before = set(registry_module._registered_modules)
    _register("guard_udf_that_explodes_1315", guard_udf_that_explodes_1315)
    try:
        result = GuardEvaluator()._evaluate_conditional_clause(
            {"a": 1}, "guard_udf_that_explodes_1315", passthrough_on_error=False
        )
    finally:
        _unregister("guard_udf_that_explodes_1315", modules_before)

    assert result is not None
    assert result.should_execute is False
    assert result.behavior.value == "skip"


def test_evaluator_still_passes_when_udf_raises_and_passthrough_on_error_true():
    def guard_udf_that_explodes_1315b(data):
        raise RuntimeError("boom")

    modules_before = set(registry_module._registered_modules)
    _register("guard_udf_that_explodes_1315b", guard_udf_that_explodes_1315b)
    try:
        result = GuardEvaluator()._evaluate_conditional_clause(
            {"a": 1}, "guard_udf_that_explodes_1315b", passthrough_on_error=True
        )
    finally:
        _unregister("guard_udf_that_explodes_1315b", modules_before)

    assert result is None


def test_evaluate_wires_the_flag_through_to_conditional_clause():
    evaluator = GuardEvaluator()
    with patch.object(evaluator, "_evaluate_conditional_clause") as mocked:
        mocked.return_value = None
        evaluator.evaluate(
            item={},
            guard_config=None,
            context=None,
            conditional_clause="some_udf",
            conditional_clause_passthrough_on_error=False,
        )
    mocked.assert_called_once_with({}, "some_udf", passthrough_on_error=False)
