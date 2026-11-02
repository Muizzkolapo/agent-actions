"""Schema compilation must honour a declared additionalProperties, defaulting to strict."""

import jsonschema
import pytest

from agent_actions.errors import SchemaValidationError
from agent_actions.output.response.expander_schema import compile_output_schema
from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.utils.udf_management.tooling import _validate_against_schema

_UNIFIED = {"name": "s", "fields": [{"id": "a", "type": "string"}]}


@pytest.mark.parametrize("vendor", ["openai", "groq", "agac-provider"])
def test_json_schema_vendor_honours_true(vendor):
    compiled = compile_unified_schema({**_UNIFIED, "additionalProperties": True}, vendor)
    assert compiled["schema"]["additionalProperties"] is True


def test_openai_defaults_false_when_absent():
    compiled = compile_unified_schema(_UNIFIED, "openai")
    assert compiled["schema"]["additionalProperties"] is False


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


def test_udf_output_extra_key_accepted_when_true():
    schema = compile_unified_schema({**_UNIFIED, "additionalProperties": True}, "openai")["schema"]
    _validate_against_schema({"a": "x", "extra": 1}, schema, "udf", validation_type="output")


def test_udf_output_extra_key_rejected_when_default():
    schema = compile_unified_schema(_UNIFIED, "openai")["schema"]
    with pytest.raises(SchemaValidationError):
        _validate_against_schema({"a": "x", "extra": 1}, schema, "udf", validation_type="output")


def _compile_root_array(root_flag, item=None):
    """The record schema of a root array schema that sets *root_flag* at its root (1610)."""
    schema = {"type": "array", "items": item or {"type": "object", "properties": {"a": {}}}}
    if root_flag is not None:
        schema["additionalProperties"] = root_flag
    agent = {"agent_type": "act", "schema": schema}
    compile_output_schema(agent, {})
    return agent["json_output_schema"]


def test_a_root_array_flag_covers_its_records():
    record = _compile_root_array(True)
    assert record["additionalProperties"] is True
    _validate_against_schema({"a": "x", "carried": 1}, record, "udf", validation_type="output")


def test_a_root_array_without_the_flag_stays_strict():
    record = _compile_root_array(None)
    with pytest.raises(SchemaValidationError):
        _validate_against_schema({"a": "x", "carried": 1}, record, "udf", validation_type="output")


def test_the_records_own_flag_wins_over_the_root():
    item = {"type": "object", "properties": {"a": {}}, "additionalProperties": False}
    assert _compile_root_array(True, item)["additionalProperties"] is False


def test_records_with_properties_and_no_type_take_the_flag_too():
    assert _compile_root_array(None, {"properties": {"a": {}}})["additionalProperties"] is False
    assert _compile_root_array(True, {"properties": {"a": {}}})["additionalProperties"] is True
