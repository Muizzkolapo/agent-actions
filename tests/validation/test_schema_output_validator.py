"""Unit tests for schema_output_validator module."""

import pytest
from datetime import datetime

from agent_actions.validation.schema_output_validator import (
    SchemaValidationReport,
    validate_output_against_schema,
    validate_and_raise_if_invalid,
)
from agent_actions.errors import SchemaValidationError


class TestSchemaValidationReport:
    """Tests for SchemaValidationReport dataclass."""

    def test_compliant_report(self):
        """Test creating a compliant validation report."""
        report = SchemaValidationReport(
            action_name="test_action",
            schema_name="test_schema",
            is_compliant=True,
            expected_fields={"name", "age"},
            actual_fields={"name", "age"},
        )
        assert report.is_compliant
        assert report.action_name == "test_action"
        assert report.schema_name == "test_schema"
        assert len(report.missing_required) == 0
        assert len(report.extra_fields) == 0

    def test_non_compliant_report(self):
        """Test creating a non-compliant validation report."""
        report = SchemaValidationReport(
            action_name="test_action",
            schema_name="test_schema",
            is_compliant=False,
            expected_fields={"name", "age"},
            actual_fields={"name"},
            missing_required=["age"],
        )
        assert not report.is_compliant
        assert "age" in report.missing_required

    def test_format_report(self):
        """Test formatting a validation report."""
        report = SchemaValidationReport(
            action_name="test_action",
            schema_name="test_schema",
            is_compliant=False,
            missing_required=["required_field"],
            extra_fields=["unknown_field"],
            type_errors={"age": ("integer", "string")},
            validation_errors=["Missing required field"],
        )
        formatted = report.format_report()
        assert "test_action" in formatted
        assert "test_schema" in formatted
        assert "INVALID" in formatted
        assert "required_field" in formatted
        assert "unknown_field" in formatted

    def test_to_dict(self):
        """Test converting report to dictionary."""
        report = SchemaValidationReport(
            action_name="test_action",
            schema_name="test_schema",
            is_compliant=True,
        )
        result = report.to_dict()
        assert result["action_name"] == "test_action"
        assert result["schema_name"] == "test_schema"
        assert result["is_compliant"] is True
        assert "timestamp" in result


class TestValidateOutputAgainstSchema:
    """Tests for validate_output_against_schema function."""

    def test_valid_output_unified_format(self):
        """Test validation with valid output against unified schema format."""
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "number", "required": False},
            ],
        }
        output = {"name": "John", "age": 30}

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant
        assert report.expected_fields == {"name", "age"}
        assert report.actual_fields == {"name", "age"}
        assert len(report.missing_required) == 0

    def test_missing_required_field(self):
        """Test validation fails when required field is missing."""
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "number", "required": True},
            ],
        }
        output = {"name": "John"}  # Missing 'age'

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "age" in report.missing_required

    def test_missing_optional_field(self):
        """Test validation passes when optional field is missing."""
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "number", "required": False},
            ],
        }
        output = {"name": "John"}  # Missing optional 'age'

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant
        assert "age" in report.missing_optional

    def test_extra_fields_non_strict(self):
        """Test extra fields don't fail validation in non-strict mode."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John", "extra": "value"}

        report = validate_output_against_schema(output, schema, "test_action", strict_mode=False)

        assert report.is_compliant
        assert "extra" in report.extra_fields

    def test_extra_fields_strict(self):
        """Test extra fields fail validation in strict mode."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John", "extra": "value"}

        report = validate_output_against_schema(output, schema, "test_action", strict_mode=True)

        assert not report.is_compliant
        assert "extra" in report.extra_fields

    def test_type_mismatch(self):
        """Test type mismatch is detected."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "age", "type": "integer", "required": True}],
        }
        output = {"age": "not a number"}

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "age" in report.type_errors
        assert report.type_errors["age"] == ("integer", "str")

    def test_json_schema_format(self):
        """Test validation with JSON Schema format."""
        schema = {
            "name": "test_schema",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        output = {"name": "John", "age": 30}

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant
        assert "name" in report.expected_fields
        assert "age" in report.expected_fields

    def test_array_schema_format(self):
        """Test validation with array schema format."""
        schema = {
            "name": "items",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "value": {"type": "number"},
                },
                "required": ["id"],
            },
        }
        output = [{"id": "1", "value": 10}]

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant

    def test_nested_openai_schema_format(self):
        """Test validation with nested OpenAI-style schema format."""
        schema = {
            "name": "test_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "result": {"type": "string"},
                },
                "required": ["result"],
            },
        }
        output = {"result": "success"}

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant


class TestValidateAndRaiseIfInvalid:
    """Tests for validate_and_raise_if_invalid function."""

    def test_valid_output_returns_report(self):
        """Test valid output returns report without raising."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John"}

        report = validate_and_raise_if_invalid(output, schema, "test_action")

        assert report.is_compliant

    def test_invalid_output_raises_error(self):
        """Test invalid output raises SchemaValidationError."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {}  # Missing required 'name'

        with pytest.raises(SchemaValidationError) as exc_info:
            validate_and_raise_if_invalid(output, schema, "test_action")

        error = exc_info.value
        assert error.schema_name == "test_schema"
        assert error.action_name == "test_action"
        assert "name" in error.missing_fields

    def test_strict_mode_fails_on_extra_fields(self):
        """Test strict mode raises error on extra fields."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John", "extra": "value"}

        with pytest.raises(SchemaValidationError) as exc_info:
            validate_and_raise_if_invalid(output, schema, "test_action", strict_mode=True)

        error = exc_info.value
        assert "extra" in error.extra_fields
