"""A ``type: object`` JSON Schema compiles to the same schema its ``fields:`` twin does (1346)."""

from __future__ import annotations

import pytest

from agent_actions.output.response.context_data import _load_inline_schema
from agent_actions.output.response.vendor_compilation import compile_unified_schema

OBJECT_FORM = {
    "name": "page_summary",
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "One line"},
        "tone": {"type": "string", "enum": ["formal", "casual"]},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}

FIELDS_FORM = {
    "name": "page_summary",
    "fields": [
        {"id": "summary", "type": "string", "description": "One line", "required": True},
        {"id": "tone", "type": "string", "enum": ["formal", "casual"], "required": False},
        {"id": "tags", "type": "array", "items": {"type": "string"}, "required": False},
    ],
}


def test_object_form_compiles_to_the_properties_it_declares():
    compiled = compile_unified_schema(dict(OBJECT_FORM), "openai")["schema"]

    assert set(compiled["properties"]) == {"summary", "tone", "tags"}
    assert compiled["properties"]["tone"]["enum"] == ["formal", "casual"]
    assert compiled["required"] == ["summary"]


def test_object_form_equals_its_fields_twin_for_every_vendor():
    for vendor in ("openai", "anthropic", "gemini", "ollama_local", "cohere"):
        assert compile_unified_schema(dict(OBJECT_FORM), vendor) == compile_unified_schema(
            dict(FIELDS_FORM), vendor
        ), vendor


def test_object_form_listed_required_wins_over_project_required_by_default():
    """JSON Schema: a property not in ``required`` is optional, whatever the project default."""
    schema = {**OBJECT_FORM, "required_by_default": True}

    compiled = compile_unified_schema(schema, "openai")["schema"]

    assert compiled["required"] == ["summary"]


def test_object_form_with_no_required_list_has_no_required_properties():
    schema = {k: v for k, v in OBJECT_FORM.items() if k != "required"}

    compiled = compile_unified_schema(schema, "openai")["schema"]

    assert compiled["required"] == []


@pytest.mark.parametrize("schema", [OBJECT_FORM, FIELDS_FORM], ids=["object", "fields"])
def test_a_compiled_schema_is_not_parsed_as_inline_shorthand(schema):
    base, name = _load_inline_schema(dict(schema), None, "{}", {"name": "act"}, {})

    assert base == schema
    assert name == "act"


def test_array_form_is_not_parsed_as_inline_shorthand():
    array_form = {
        "name": "facts",
        "type": "array",
        "items": {"type": "object", "properties": {"fact": {"type": "string"}}},
    }

    base, _ = _load_inline_schema(dict(array_form), None, "{}", {"name": "act"}, {})

    assert base == array_form


@pytest.mark.parametrize(
    ("schema", "fragment"),
    [
        (
            {
                "name": "s",
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": "a",
            },
            "expected a list",
        ),
        (
            {
                "name": "s",
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a", "missing"],
            },
            "'missing'",
        ),
        ({"name": "s", "type": "object", "properties": {"a": {"description": "x"}}}, "'a'"),
    ],
    ids=["required_not_a_list", "required_names_undeclared_property", "property_without_type"],
)
def test_a_malformed_object_form_is_refused_naming_the_schema(schema, fragment):
    from agent_actions.errors import SchemaValidationError

    with pytest.raises(SchemaValidationError) as raised:
        compile_unified_schema(schema, "openai")

    assert "'s'" in str(raised.value)
    assert fragment in str(raised.value)


def test_shorthand_with_fields_named_type_and_properties_is_still_shorthand():
    shorthand = {"type": "string!", "properties": "array[string]"}

    base, _ = _load_inline_schema(dict(shorthand), None, "{}", {"name": "act"}, {})
    compiled = compile_unified_schema(base, "openai")["schema"]

    assert set(compiled["properties"]) == {"type", "properties"}
    assert compiled["required"] == ["type"]


def test_a_nested_object_property_keeps_its_properties_and_required_list():
    schema = {
        "name": "s",
        "type": "object",
        "properties": {
            "metadata": {
                "type": "object",
                "properties": {"created_at": {"type": "string"}, "version": {"type": "integer"}},
                "required": ["created_at"],
            }
        },
        "required": ["metadata"],
    }

    compiled = compile_unified_schema(schema, "openai")["schema"]

    assert compiled["properties"]["metadata"] == {
        "type": "object",
        "properties": {"created_at": {"type": "string"}, "version": {"type": "integer"}},
        "required": ["created_at"],
    }
    assert compiled["required"] == ["metadata"]


def test_a_nested_object_listed_nowhere_is_optional_though_it_carries_a_required_list():
    schema = {
        "name": "s",
        "type": "object",
        "properties": {
            "metadata": {
                "type": "object",
                "properties": {"created_at": {"type": "string"}},
                "required": ["created_at"],
            }
        },
    }

    compiled = compile_unified_schema(schema, "openai")["schema"]

    assert compiled["required"] == []
