"""Cached JSON Schema validators report exactly what jsonschema.validate does."""

import jsonschema
import pytest

from agent_actions.errors import SchemaValidationError
from agent_actions.utils import jsonschema_cache
from agent_actions.utils.jsonschema_cache import validate as _check_against_schema
from agent_actions.utils.udf_management.tooling import _validate_against_schema

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name"],
    "additionalProperties": False,
}

INVALID_INSTANCES = [
    {},
    {"name": 3},
    {"name": "a", "tags": ["x", 4]},
    {"name": "a", "extra": True},
    {"name": 1, "tags": [1], "extra": 2},
    "not-an-object",
]


@pytest.mark.parametrize("instance", INVALID_INSTANCES)
def test_reports_the_same_error_as_jsonschema_validate(instance):
    with pytest.raises(jsonschema.ValidationError) as expected:
        jsonschema.validate(instance=instance, schema=SCHEMA)
    with pytest.raises(jsonschema.ValidationError) as actual:
        _check_against_schema(instance, SCHEMA)

    assert actual.value.message == expected.value.message
    assert list(actual.value.path) == list(expected.value.path)
    assert actual.value.schema == expected.value.schema


def test_valid_instance_passes():
    _check_against_schema({"name": "a", "tags": ["x"]}, SCHEMA)


def test_invalid_schema_raises_on_every_call():
    bad = {"type": "no-such-type"}
    for _ in range(2):
        with pytest.raises(jsonschema.SchemaError):
            _check_against_schema({}, bad)


def test_mutating_a_schema_dict_is_not_served_stale():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    _check_against_schema({"n": 1}, schema)

    schema["properties"]["n"]["type"] = "string"
    with pytest.raises(jsonschema.ValidationError):
        _check_against_schema({"n": 1}, schema)


def test_validator_is_reused_across_calls():
    jsonschema_cache._build.cache_clear()
    for _ in range(5):
        _check_against_schema({"name": "a"}, SCHEMA)
    info = jsonschema_cache._build.cache_info()
    assert info.misses == 1
    assert info.hits == 4


def test_non_json_schema_still_validates():
    schema = {"type": "object", "properties": {"n": {"enum": [1, 2]}}, "x-meta": object()}
    _check_against_schema({"n": 1}, schema)
    with pytest.raises(jsonschema.ValidationError):
        _check_against_schema({"n": 3}, schema)


def test_udf_error_wrapping_is_unchanged():
    with pytest.raises(SchemaValidationError) as exc:
        _validate_against_schema(
            {"name": "a", "tags": ["x", 4]},
            SCHEMA,
            "my_udf",
            item_index=2,
            validation_type="output",
        )
    assert "Output schema validation failed for UDF 'my_udf' (item 2) at tags -> 1" in str(
        exc.value
    )


def test_explicit_validator_class_is_part_of_the_cache_key():
    schema = {"type": "string"}
    draft7 = jsonschema_cache.checked_validator(schema, jsonschema.Draft7Validator)
    draft2020 = jsonschema_cache.checked_validator(schema, jsonschema.Draft202012Validator)
    assert isinstance(draft7, jsonschema.Draft7Validator)
    assert isinstance(draft2020, jsonschema.Draft202012Validator)
