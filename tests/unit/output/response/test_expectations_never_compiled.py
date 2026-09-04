"""The compiled provider schema never carries the expectations: block."""

import json

import pytest

from agent_actions.output.response.vendor_compilation import (
    SUPPORTED_VENDORS,
    compile_unified_schema,
)

_UNIFIED = {
    "name": "scenario_question",
    "fields": [{"id": "options", "type": "array", "items": {"type": "string"}}],
    "expectations": [
        {"id": "option_count", "type": "item_count", "field": "options", "params": {"equals": 4}}
    ],
}

_FIELD_SCOPED = {
    "name": "scenario_question",
    "fields": [
        {
            "id": "options",
            "type": "array",
            "items": {"type": "string"},
            "expectations": [{"id": "option_count", "type": "item_count", "params": {"equals": 4}}],
        }
    ],
}


@pytest.mark.parametrize("target", sorted(SUPPORTED_VENDORS))
def test_compiled_schema_never_contains_expectations(target):
    compiled = compile_unified_schema(_UNIFIED, target)
    assert "options" in json.dumps(compiled)
    assert "expectations" not in json.dumps(compiled)
    assert "option_count" not in json.dumps(compiled)


@pytest.mark.parametrize("target", sorted(SUPPORTED_VENDORS))
def test_a_rule_declared_on_a_field_never_reaches_the_provider(target):
    compiled = json.dumps(compile_unified_schema(_FIELD_SCOPED, target))
    assert "options" in compiled
    assert "expectations" not in compiled
    assert "option_count" not in compiled


_NESTED = {
    "name": "scenario_question",
    "fields": [
        {
            "id": "options",
            "type": "array",
            "expectations": [{"id": "option_count", "type": "item_count", "params": {"equals": 4}}],
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "expectations": [{"id": "text_present", "type": "not_null"}],
                    }
                },
            },
        }
    ],
}


@pytest.mark.parametrize("target", sorted(SUPPORTED_VENDORS))
def test_a_rule_below_a_field_never_reaches_the_provider(target):
    compiled = json.dumps(compile_unified_schema(_NESTED, target))
    assert "text" in compiled
    assert "expectations" not in compiled
    assert "text_present" not in compiled
