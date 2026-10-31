"""Regression tests for type validation of the 'properties' field in schema output validator.

Ensures that malformed 'properties' values (null, string, list, etc.) produce a
validation error instead of crashing with an AttributeError or TypeError.
"""

import pytest

from agent_actions.validation.schema_output_validator import (
    validate_output_against_schema,
)


@pytest.mark.parametrize(
    ("schema", "llm_output", "fragments"),
    [
        pytest.param(
            {"name": "test_schema", "properties": None},
            {"foo": "bar"},
            ("properties", "dict"),
            id="null",
        ),
        pytest.param(
            {"name": "test_schema", "properties": "invalid"},
            {"foo": "bar"},
            ("properties", "str"),
            id="string",
        ),
        pytest.param(
            {"name": "test_schema", "properties": [1, 2]},
            {},
            ("properties", "list"),
            id="list",
        ),
        pytest.param(
            {
                "name": "array_schema",
                "type": "array",
                "items": {"type": "object", "properties": None},
            },
            [{"foo": "bar"}],
            ("items", "properties"),
            id="items-null",
        ),
        pytest.param(
            {
                "name": "array_schema",
                "type": "array",
                "items": {"type": "object", "properties": "bad"},
            },
            [{"foo": "bar"}],
            ("items", "str"),
            id="items-string",
        ),
        # nested schema wrapper, e.g. the OpenAI compiled format
        pytest.param(
            {"name": "nested_schema", "schema": {"properties": None}},
            {"foo": "bar"},
            ("properties",),
            id="nested-null",
        ),
    ],
)
def test_malformed_properties_returns_non_compliant_report(schema, llm_output, fragments):
    report = validate_output_against_schema(
        llm_output=llm_output,
        schema=schema,
        action_name="test_action",
    )
    assert not report.is_compliant
    assert any(all(f in e for f in fragments) for e in report.validation_errors)


class TestPropertiesValidEmptyDict:
    """Schema with properties: {} should work normally (no fields expected)."""

    def test_is_compliant_with_empty_output(self):
        schema = {"name": "test_schema", "properties": {}}
        report = validate_output_against_schema(
            llm_output={},
            schema=schema,
            action_name="test_action",
        )
        assert report.is_compliant
        assert report.validation_errors == []

    def test_is_compliant_with_extra_output(self):
        """Extra fields are allowed in non-strict mode."""
        schema = {"name": "test_schema", "properties": {}}
        report = validate_output_against_schema(
            llm_output={"extra": "value"},
            schema=schema,
            action_name="test_action",
        )
        assert report.is_compliant


class TestPropertiesValidPopulatedDict:
    """Schema with a proper properties dict should validate normally."""

    def test_compliant_output(self):
        schema = {
            "name": "test_schema",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        report = validate_output_against_schema(
            llm_output={"name": "Alice", "age": 30},
            schema=schema,
            action_name="test_action",
        )
        assert report.is_compliant
        assert report.validation_errors == []

    def test_missing_required_field(self):
        schema = {
            "name": "test_schema",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        }
        report = validate_output_against_schema(
            llm_output={},
            schema=schema,
            action_name="test_action",
        )
        assert not report.is_compliant
        assert report.missing_required == ["name"]
