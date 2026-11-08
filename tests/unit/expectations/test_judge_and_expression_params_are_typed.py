"""llm_judge, expression and row_condition params are held to their types like a built-in's.

They declared no types, so ``rule: ["be concise"]`` and ``condition: 5`` passed
preflight and then failed or misbehaved at run time.
"""

import pytest
from pydantic import ValidationError

from agent_actions.expectations import registry
from agent_actions.expectations.loader import build_inline_suite
from agent_actions.validation.expectations_validator import find_expectation_defects


def _preflight(entry: dict) -> list[str]:
    configs = {"write_q": {"expect": {"expectations": [{"id": "r", **entry}]}}}
    return find_expectation_defects(configs, {"write_q": {"answer", "score"}}).get("write_q", [])


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        pytest.param(
            {"type": "llm_judge", "field": "answer", "params": {"rule": ["be concise"]}},
            "type 'llm_judge' takes parameter 'rule' as a string, got list ['be concise']",
            id="judge-rule-list",
        ),
        pytest.param(
            {"type": "llm_judge", "field": "answer", "params": {"rule": "x", "model": 4}},
            "type 'llm_judge' takes parameter 'model' as a string, got int 4",
            id="judge-model-int",
        ),
        pytest.param(
            {"type": "expression", "params": {"condition": 5}},
            "type 'expression' takes parameter 'condition' as a string, got int 5",
            id="expression-condition-int",
        ),
        pytest.param(
            {"type": "not_null", "field": "answer", "params": {"row_condition": True}},
            "type 'not_null' takes parameter 'row_condition' as a string, got bool True",
            id="row-condition-bool",
        ),
    ],
)
def test_preflight_and_runtime_refuse_a_param_of_the_wrong_type(entry, message):
    assert any(message in defect for defect in _preflight(entry))
    with pytest.raises(ValidationError) as caught:
        build_inline_suite([entry], "write_q")
    assert message in str(caught.value)


def test_a_string_context_is_not_told_params_are_literals():
    entry = {"type": "llm_judge", "field": "answer", "params": {"rule": "x", "context": "a.b"}}

    (defect,) = _preflight(entry)

    assert defect.endswith("takes parameter 'context' as a list, got str 'a.b'")


def test_a_null_context_is_absent_at_preflight():
    entry = {"type": "llm_judge", "field": "answer", "params": {"rule": "x", "context": None}}

    assert _preflight(entry) == []


def test_well_typed_judge_and_expression_rules_pass_preflight():
    judge = {
        "type": "llm_judge",
        "field": "answer",
        "params": {"rule": "be concise", "model": "gpt-4o-mini", "votes": 3, "context": []},
    }
    expression = {"type": "expression", "params": {"condition": "score >= 80"}}

    assert _preflight(judge) == []
    assert _preflight(expression) == []


def test_a_user_types_row_condition_is_checked():
    name = "user_type_with_a_row_condition"
    try:
        registry.expectation_check(name, params=("anything",))(lambda value, params: (True, ""))

        with pytest.raises(ValidationError) as caught:
            build_inline_suite(
                [{"type": name, "field": "x", "params": {"row_condition": 1}}], "write_q"
            )

        assert f"type '{name}' takes parameter 'row_condition' as a string, got int 1" in str(
            caught.value
        )
    finally:
        registry._REGISTRY.pop(name, None)
        registry._USER_CHECK_SOURCES.pop(name, None)
