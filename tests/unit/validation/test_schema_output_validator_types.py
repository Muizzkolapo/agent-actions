"""Regression tests for type validation of the 'properties' field in schema output validator.

Ensures that malformed 'properties' values (null, string, list, etc.) produce a
validation error instead of crashing with an AttributeError or TypeError.
"""

import pytest

from agent_actions.errors import SchemaValidationError
from agent_actions.validation.schema_output_validator import (
    validate_and_raise_if_invalid,
    validate_output_against_schema,
)

# ---------------------------------------------------------------------------
# Direct 'properties' field on a JSON-Schema-style schema
# ---------------------------------------------------------------------------


class TestPropertiesNull:
    """Schema with properties: null should produce a validation error, not crash."""

    def test_returns_non_compliant_report(self):
        schema = {"name": "test_schema", "properties": None}
        report = validate_output_against_schema(
            llm_output={"foo": "bar"},
            schema=schema,
            action_name="test_action",
        )
        assert not report.is_compliant
        assert any("properties" in e and "dict" in e for e in report.validation_errors)

    def test_raise_variant(self):
        schema = {"name": "test_schema", "properties": None}
        with pytest.raises(SchemaValidationError):
            validate_and_raise_if_invalid(
                llm_output={"foo": "bar"},
                schema=schema,
                action_name="test_action",
            )


class TestPropertiesInvalidString:
    """Schema with properties: "invalid" should produce a validation error, not crash."""

    def test_returns_non_compliant_report(self):
        schema = {"name": "test_schema", "properties": "invalid"}
        report = validate_output_against_schema(
            llm_output={"foo": "bar"},
            schema=schema,
            action_name="test_action",
        )
        assert not report.is_compliant
        assert any("properties" in e and "str" in e for e in report.validation_errors)

    def test_raise_variant(self):
        schema = {"name": "test_schema", "properties": "invalid"}
        with pytest.raises(SchemaValidationError):
            validate_and_raise_if_invalid(
                llm_output={"foo": "bar"},
                schema=schema,
                action_name="test_action",
            )


class TestPropertiesInvalidList:
    """Schema with properties: [1, 2] should produce a validation error, not crash."""

    def test_returns_non_compliant_report(self):
        schema = {"name": "test_schema", "properties": [1, 2]}
        report = validate_output_against_schema(
            llm_output={},
            schema=schema,
            action_name="test_action",
        )
        assert not report.is_compliant
        assert any("properties" in e and "list" in e for e in report.validation_errors)


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


# ---------------------------------------------------------------------------
# Nested 'properties' inside array items
# ---------------------------------------------------------------------------


class TestArrayItemsPropertiesNull:
    """Array schema with items.properties: null should produce a validation error."""

    def test_returns_non_compliant_report(self):
        schema = {
            "name": "array_schema",
            "type": "array",
            "items": {"type": "object", "properties": None},
        }
        report = validate_output_against_schema(
            llm_output=[{"foo": "bar"}],
            schema=schema,
            action_name="test_action",
        )
        assert not report.is_compliant
        assert any("items" in e and "properties" in e for e in report.validation_errors)


class TestArrayItemsPropertiesInvalidString:
    """Array schema with items.properties: "bad" should produce a validation error."""

    def test_returns_non_compliant_report(self):
        schema = {
            "name": "array_schema",
            "type": "array",
            "items": {"type": "object", "properties": "bad"},
        }
        report = validate_output_against_schema(
            llm_output=[{"foo": "bar"}],
            schema=schema,
            action_name="test_action",
        )
        assert not report.is_compliant
        assert any("items" in e and "str" in e for e in report.validation_errors)


# ---------------------------------------------------------------------------
# Nested schema wrapper (e.g., OpenAI compiled format)
# ---------------------------------------------------------------------------


class TestNestedSchemaPropertiesNull:
    """Nested schema wrapper with inner properties: null should be caught."""

    def test_returns_non_compliant_report(self):
        schema = {
            "name": "nested_schema",
            "schema": {"properties": None},
        }
        report = validate_output_against_schema(
            llm_output={"foo": "bar"},
            schema=schema,
            action_name="test_action",
        )
        assert not report.is_compliant
        assert any("properties" in e for e in report.validation_errors)
