"""Integration tests for UDF output validation via json_output_schema parameter.

Tests the full flow: register UDF -> execute -> validate output against a
JSON Schema passed to execute_user_defined_function().

Output schemas are now defined exclusively via YAML schema: in workflow configs.
The json_output_schema parameter replaces the removed output_type decorator arg.
"""

import pytest

from agent_actions.errors import SchemaValidationError
from agent_actions.utils.udf_management.registry import (
    clear_registry,
    udf_tool,
)
from agent_actions.utils.udf_management.tooling import execute_user_defined_function


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


# Reusable JSON schemas
SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"result": {"type": "string"}},
    "required": ["result"],
    "additionalProperties": False,
}

LIST_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
    "required": ["items"],
    "additionalProperties": False,
}

OPTIONAL_SCHEMA = {
    "type": "object",
    "properties": {
        "required": {"type": "string"},
        "optional": {"type": "string"},
    },
    "required": ["required"],
    "additionalProperties": False,
}

DICT_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        },
    },
    "required": ["metadata"],
    "additionalProperties": False,
}

NESTED_SCHEMA = {
    "type": "object",
    "properties": {
        "inner": {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
    },
    "required": ["inner"],
    "additionalProperties": False,
}


class TestOutputValidation:
    """Tests for output schema validation."""

    def test_valid_output_passes(self):
        """Valid output should pass validation."""

        @udf_tool()
        def process(data):
            return {"result": "processed"}

        result = execute_user_defined_function(
            "process", {"text": "hello"}, json_output_schema=SIMPLE_SCHEMA
        )
        assert result == {"result": "processed"}

    def test_invalid_output_raises(self):
        """Invalid output should raise SchemaValidationError."""

        @udf_tool()
        def bad_process(data):
            return {"wrong_field": "value"}  # Missing 'result' field

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "bad_process", {"text": "hello"}, json_output_schema=SIMPLE_SCHEMA
            )

        assert "output" in str(exc_info.value).lower() or "result" in str(exc_info.value)

    def test_output_validation_disabled(self):
        """Output validation can be disabled."""

        @udf_tool()
        def process(data):
            return {"wrong": "output"}  # Would fail validation

        # Should not raise when validation is disabled
        result = execute_user_defined_function("process", {"text": "hello"}, validate_output=False)
        assert result == {"wrong": "output"}

    def test_no_output_schema_skips_validation(self):
        """Without json_output_schema, output validation is skipped."""

        @udf_tool()
        def process(data):
            return {"anything": "goes"}

        # Should not raise - no output schema to validate against
        result = execute_user_defined_function("process", {"text": "hello"})
        assert result == {"anything": "goes"}


class TestComplexOutputTypes:
    """Tests for complex output type handling."""

    def test_list_field_in_output(self):
        """List[T] field in output should work."""

        @udf_tool()
        def process(data):
            return {"items": ["a", "b", "c"]}

        result = execute_user_defined_function("process", {"x": 1}, json_output_schema=LIST_SCHEMA)
        assert result == {"items": ["a", "b", "c"]}

    def test_optional_field_in_output(self):
        """Optional field in output should not be required."""

        @udf_tool()
        def process(data):
            return {"required": "value"}  # No optional field

        # Should work without optional field
        result = execute_user_defined_function(
            "process", {"x": 1}, json_output_schema=OPTIONAL_SCHEMA
        )
        assert result == {"required": "value"}

    def test_dict_field_in_output(self):
        """Dict[str, V] field in output should work."""

        @udf_tool()
        def process(data):
            return {"metadata": {"a": 1, "b": 2}}

        result = execute_user_defined_function("process", {"x": 1}, json_output_schema=DICT_SCHEMA)
        assert result == {"metadata": {"a": 1, "b": 2}}

    def test_nested_object_in_output(self):
        """Nested object in output should work."""

        @udf_tool()
        def process(data):
            return {"inner": {"value": 42}}

        result = execute_user_defined_function(
            "process", {"x": 1}, json_output_schema=NESTED_SCHEMA
        )
        assert result == {"inner": {"value": 42}}
