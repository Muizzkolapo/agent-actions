"""Unit tests for schema_output_validator module."""

import pytest

from agent_actions.errors import SchemaValidationError
from agent_actions.validation.schema_output_validator import (
    SchemaValidationReport,
    validate_and_raise_if_invalid,
    validate_output_against_schema,
)


class TestSchemaValidationReport:
    """Tests for SchemaValidationReport dataclass."""

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

    def test_bool_rejected_for_integer_type(self):
        """Test that bool values are rejected for integer type (bool subclasses int in Python)."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "count", "type": "integer", "required": True}],
        }
        output = {"count": True}

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "count" in report.type_errors
        assert report.type_errors["count"] == ("integer", "bool")

    def test_bool_rejected_for_number_type(self):
        """Test that bool values are rejected for number type (bool subclasses int/float in Python)."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "score", "type": "number", "required": True}],
        }
        output = {"score": False}

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "score" in report.type_errors
        assert report.type_errors["score"] == ("number", "bool")

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


class TestNamespacedKeyHint:
    """Regression: detect action-namespaced output from tool UDFs."""

    def test_namespaced_output_produces_hint(self):
        """When output has dict-valued extra keys and missing required fields, hint at namespacing."""
        schema = {
            "name": "flatten_schema",
            "fields": [
                {"id": "question_text", "type": "string", "required": True},
                {"id": "answer_text", "type": "string", "required": True},
            ],
        }
        # UDF passed through namespaced input instead of unwrapping
        output = {"canonicalize_qa": {"question_text": "What?", "answer_text": "Yes"}}

        report = validate_output_against_schema(output, schema, "flatten_questions")
        assert not report.is_compliant
        assert "question_text" in report.missing_required
        assert "canonicalize_qa" in report.extra_fields
        assert any("action namespaces" in e for e in report.validation_errors)

    def test_no_hint_when_extra_fields_are_not_dicts(self):
        """Extra scalar fields should NOT trigger the namespace hint."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"wrong_field": "value"}

        report = validate_output_against_schema(output, schema, "test_action")
        assert not report.is_compliant
        assert not any("action namespaces" in e for e in report.validation_errors)

    def test_no_hint_when_no_missing_fields(self):
        """If all required fields are present, no namespace hint even with extra dict keys."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John", "extra_action": {"nested": "data"}}

        report = validate_output_against_schema(output, schema, "test_action")
        assert report.is_compliant
        assert not any("action namespaces" in e for e in report.validation_errors)
