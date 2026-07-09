"""Schema compilation must honour a declared additionalProperties, defaulting to strict."""

import jsonschema
import pytest

from agent_actions.output.response.expander_schema import compile_output_schema
from agent_actions.output.response.vendor_compilation import compile_unified_schema

_UNIFIED = {"name": "s", "fields": [{"id": "a", "type": "string"}]}


def test_openai_honours_true():
    compiled = compile_unified_schema({**_UNIFIED, "additionalProperties": True}, "openai")
    assert compiled["schema"]["additionalProperties"] is True


def test_openai_defaults_false_when_absent():
    compiled = compile_unified_schema(_UNIFIED, "openai")
    assert compiled["schema"]["additionalProperties"] is False


def test_groq_honours_true():
    compiled = compile_unified_schema({**_UNIFIED, "additionalProperties": True}, "groq")
    assert compiled["schema"]["additionalProperties"] is True


def test_agac_provider_honours_true():
    compiled = compile_unified_schema({**_UNIFIED, "additionalProperties": True}, "agac-provider")
    assert compiled["schema"]["additionalProperties"] is True


def test_anthropic_honours_true():
    compiled = compile_unified_schema({**_UNIFIED, "additionalProperties": True}, "anthropic")
    assert compiled[0]["input_schema"]["additionalProperties"] is True


def test_anthropic_defaults_false_when_absent():
    compiled = compile_unified_schema(_UNIFIED, "anthropic")
    assert compiled[0]["input_schema"]["additionalProperties"] is False


def test_ollama_honours_true():
    compiled = compile_unified_schema({**_UNIFIED, "additionalProperties": True}, "ollama_local")
    assert compiled["additionalProperties"] is True


def test_ollama_defaults_false_when_absent():
    compiled = compile_unified_schema(_UNIFIED, "ollama_local")
    assert compiled["additionalProperties"] is False


def test_extra_key_validates_when_true():
    compiled = compile_unified_schema({**_UNIFIED, "additionalProperties": True}, "openai")
    jsonschema.validate({"a": "x", "steps": ["1"]}, compiled["schema"])


def test_extra_key_rejected_when_default():
    compiled = compile_unified_schema(_UNIFIED, "openai")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"a": "x", "steps": ["1"]}, compiled["schema"])


def _compile_array_item(item_additional_properties):
    item = {"type": "object", "properties": {"a": {"type": "string"}}}
    if item_additional_properties is not None:
        item["additionalProperties"] = item_additional_properties
    agent = {"agent_type": "act", "schema": {"type": "array", "items": item}}
    compile_output_schema(agent, {})
    return agent["json_output_schema"]["additionalProperties"]


def test_array_item_honours_true():
    assert _compile_array_item(True) is True


def test_array_item_defaults_false_when_absent():
    assert _compile_array_item(None) is False
