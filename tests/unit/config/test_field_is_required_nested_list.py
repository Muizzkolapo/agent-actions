"""A list under a field's ``required`` is a nested object's property list, not the field's flag (1346)."""

from __future__ import annotations

import pytest

from agent_actions.config.schema_field import field_is_required
from agent_actions.utils.schema_utils import is_compiled_schema

NESTED = {"id": "metadata", "type": "object", "required": ["created_at"]}


@pytest.mark.parametrize(
    ("required_by_default", "schema_required", "expected"),
    [
        pytest.param(False, frozenset(), False, id="alone"),
        pytest.param(False, frozenset({"metadata"}), True, id="in_schema_required_list"),
        pytest.param(True, frozenset(), True, id="required_by_default"),
    ],
)
def test_a_nested_required_list_leaves_the_field_to_the_schema(
    required_by_default, schema_required, expected
):
    assert field_is_required(NESTED, required_by_default, schema_required) is expected


@pytest.mark.parametrize(
    ("value", "expected"), [(True, True), (False, False), (1, True), (0, False)]
)
def test_a_scalar_required_flag_still_decides(value, expected):
    assert field_is_required({"id": "a", "type": "string", "required": value}, True) is expected


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": "array[string]"},
        {"type": "string!", "properties": {"a": {"type": "string"}}},
        {"type": "string!", "properties": "array[string]"},
    ],
    ids=["properties_is_a_string", "type_is_shorthand", "both_shorthand"],
)
def test_shorthand_naming_fields_type_and_properties_is_not_compiled(schema):
    assert is_compiled_schema(schema) is False


def test_a_json_schema_object_is_compiled():
    assert is_compiled_schema({"type": "object", "properties": {"a": {"type": "string"}}}) is True
