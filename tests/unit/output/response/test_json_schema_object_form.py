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
