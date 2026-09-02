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
    "expectations": [{"id": "option_count", "type": "item_count", "field": "options", "equals": 4}],
}


@pytest.mark.parametrize("target", sorted(SUPPORTED_VENDORS))
def test_compiled_schema_never_contains_expectations(target):
    compiled = compile_unified_schema(_UNIFIED, target)
    assert "expectations" not in json.dumps(compiled)
    assert "option_count" not in json.dumps(compiled)
