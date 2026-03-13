"""
Integration tests for UDF schema validation and execution.

Tests end-to-end UDF execution with output schema validation, including:
- Output validation against schemas (fed via json_output_schema parameter)
- Granularity handling (RECORD/FILE)
- Error handling and messages

Note: Input validation is no longer performed - context_scope in workflow YAML
defines input structure and build_context handles input assembly.
Output schemas are defined via YAML schema: and compiled to json_output_schema
in agent config, then passed to execute_user_defined_function().
"""

import pytest

from agent_actions.config.schema import Granularity
from agent_actions.errors import AgentActionsError, SchemaValidationError
from agent_actions.utils.udf_management.registry import clear_registry, udf_tool
from agent_actions.utils.udf_management.tooling import execute_user_defined_function

# Reusable JSON schemas (equivalent to what YAML schema: compiles to)
TRANSFORM_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"result": {"type": "string"}},
    "required": ["result"],
    "additionalProperties": False,
}

USER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string"},
        "email": {"type": "string"},
    },
    "required": ["user_id", "email"],
    "additionalProperties": False,
}

AGE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"age": {"type": "integer"}},
    "required": ["age"],
    "additionalProperties": False,
}

NAME_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "nickname": {"type": "string"},
    },
    "required": ["name"],
    "additionalProperties": False,
}

TEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}

ITEM_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}

REQUIRED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"required_field": {"type": "string"}},
    "required": ["required_field"],
    "additionalProperties": False,
}


class TestOutputSchemaValidation:
    """Test output schema validation during UDF execution."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()

    def test_valid_output_passes_validation(self):
        """Test that valid output passes schema validation."""

        @udf_tool()
        def transform_text(data):
            return {"result": data["text"].upper()}

        result = execute_user_defined_function(
            "transform_text",
            {"text": "hello world"},
            json_output_schema=TRANSFORM_OUTPUT_SCHEMA,
        )

        assert result == {"result": "HELLO WORLD"}

    def test_missing_required_output_field_fails_validation(self):
        """Test that missing required output field fails validation."""

        @udf_tool()
        def process_user(data):
            return {"user_id": "123"}  # Missing email

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "process_user",
                {"data": "any"},
                json_output_schema=USER_OUTPUT_SCHEMA,
            )

        assert "validation failed" in str(exc_info.value).lower()

    def test_wrong_output_type_fails_validation(self):
        """Test that wrong output type fails validation."""

        @udf_tool()
        def return_age(data):
            return {"age": "not a number"}  # Wrong type

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "return_age",
                {"data": "any"},
                json_output_schema=AGE_OUTPUT_SCHEMA,
            )

        assert "validation failed" in str(exc_info.value).lower()

    def test_optional_output_field_can_be_missing(self):
        """Test that optional output fields can be omitted."""

        @udf_tool()
        def process_name(data):
            return {"name": "John"}  # nickname is optional

        result = execute_user_defined_function(
            "process_name",
            {"input": "any"},
            json_output_schema=NAME_OUTPUT_SCHEMA,
        )

        assert result["name"] == "John"

    def test_output_validation_can_be_disabled(self):
        """Test that output validation can be disabled."""

        @udf_tool()
        def no_validation(data):
            return {"wrong_field": "value"}  # Invalid output

        # Should not raise even with invalid output when validation disabled
        result = execute_user_defined_function(
            "no_validation", {"data": "any"}, validate_output=False
        )

        assert result == {"wrong_field": "value"}


class TestGranularityHandling:
    """Test granularity handling during execution (input shape is controlled by context_scope)."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()

    def test_record_mode_processes_dict_input(self):
        """Test that RECORD mode processes dict input."""

        @udf_tool(granularity=Granularity.RECORD)
        def record_processor(data):
            return {"processed": data["text"]}

        result = execute_user_defined_function("record_processor", {"text": "hello"})
        assert result == {"processed": "hello"}

    def test_file_mode_processes_array_input(self):
        """Test that FILE mode processes array input."""

        @udf_tool(granularity=Granularity.FILE)
        def file_processor(data):
            return [{"processed": item["text"]} for item in data]

        result = execute_user_defined_function(
            "file_processor", [{"text": "hello"}, {"text": "world"}]
        )
        assert len(result) == 2
        assert result[0] == {"processed": "hello"}
        assert result[1] == {"processed": "world"}

    def test_file_mode_with_output_validation(self):
        """Test FILE mode validates each output item."""

        @udf_tool(granularity=Granularity.FILE)
        def batch_multiply(data):
            return [{"value": item["value"] * 2} for item in data]

        result = execute_user_defined_function(
            "batch_multiply",
            [{"value": 1}, {"value": 2}, {"value": 3}],
            json_output_schema=ITEM_OUTPUT_SCHEMA,
        )

        assert len(result) == 3
        assert result[0]["value"] == 2
        assert result[1]["value"] == 4
        assert result[2]["value"] == 6

    def test_file_mode_invalid_output_fails(self):
        """Test FILE mode fails if any output item is invalid."""

        @udf_tool(granularity=Granularity.FILE)
        def batch_with_error(data):
            return [
                {"value": 1},
                {"wrong_field": "oops"},  # Invalid item
                {"value": 3},
            ]

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "batch_with_error",
                [{"x": 1}, {"x": 2}, {"x": 3}],
                json_output_schema=ITEM_OUTPUT_SCHEMA,
            )

        assert (
            "item 1" in str(exc_info.value).lower()
            or "validation failed" in str(exc_info.value).lower()
        )


class TestErrorHandling:
    """Test error handling and error messages."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()

    def test_execution_error_includes_context(self):
        """Test that execution errors include helpful context."""

        @udf_tool()
        def failing_function(data):
            raise ValueError("Something went wrong")

        with pytest.raises(AgentActionsError) as exc_info:
            execute_user_defined_function("failing_function", {"text": "test"})

        error_msg = str(exc_info.value)
        assert "failing_function" in error_msg
        assert "Something went wrong" in error_msg

    def test_output_validation_error_includes_schema_info(self):
        """Test that output validation errors include schema information."""

        @udf_tool()
        def needs_field(data):
            return {"wrong_field": "value"}

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "needs_field",
                {"data": "any"},
                json_output_schema=REQUIRED_OUTPUT_SCHEMA,
            )

        error_msg = str(exc_info.value)
        assert "needs_field" in error_msg
        assert "validation failed" in error_msg.lower()
