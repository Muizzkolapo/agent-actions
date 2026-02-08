"""
Integration tests for UDF schema validation and execution.

Tests end-to-end UDF execution with output schema validation, including:
- Output validation against schemas
- Granularity handling (RECORD/FILE)
- Error handling and messages

Note: Input validation is no longer performed - context_scope in workflow YAML
defines input structure and build_context handles input assembly.
"""

import pytest
from typing import Optional, TypedDict
from agent_actions.utils.udf_management.registry import udf_tool, clear_registry
from agent_actions.config.schema import Granularity
from agent_actions.utils.udf_management.tooling import execute_user_defined_function
from agent_actions.errors import SchemaValidationError, AgentActionsException


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

        class TransformOutput(TypedDict):
            result: str

        @udf_tool(output_type=TransformOutput)
        def transform_text(data):
            return {"result": data["text"].upper()}

        result = execute_user_defined_function("transform_text", {"text": "hello world"})

        assert result == {"result": "HELLO WORLD"}

    def test_missing_required_output_field_fails_validation(self):
        """Test that missing required output field fails validation."""

        class UserOutput(TypedDict):
            user_id: str
            email: str

        @udf_tool(output_type=UserOutput)
        def process_user(data):
            return {"user_id": "123"}  # Missing email

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function("process_user", {"data": "any"})

        assert "validation failed" in str(exc_info.value).lower()

    def test_wrong_output_type_fails_validation(self):
        """Test that wrong output type fails validation."""

        class AgeOutput(TypedDict):
            age: int

        @udf_tool(output_type=AgeOutput)
        def return_age(data):
            return {"age": "not a number"}  # Wrong type

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function("return_age", {"data": "any"})

        assert "validation failed" in str(exc_info.value).lower()

    def test_optional_output_field_can_be_missing(self):
        """Test that optional output fields can be omitted."""

        class NameOutput(TypedDict):
            name: str
            nickname: Optional[str]

        @udf_tool(output_type=NameOutput)
        def process_name(data):
            return {"name": "John"}  # nickname is optional

        result = execute_user_defined_function("process_name", {"input": "any"})

        assert result["name"] == "John"

    def test_output_validation_can_be_disabled(self):
        """Test that output validation can be disabled."""

        class TextOutput(TypedDict):
            text: str

        @udf_tool(output_type=TextOutput)
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

        class ItemOutput(TypedDict):
            value: int

        @udf_tool(output_type=ItemOutput, granularity=Granularity.FILE)
        def batch_multiply(data):
            return [{"value": item["value"] * 2} for item in data]

        result = execute_user_defined_function(
            "batch_multiply", [{"value": 1}, {"value": 2}, {"value": 3}]
        )

        assert len(result) == 3
        assert result[0]["value"] == 2
        assert result[1]["value"] == 4
        assert result[2]["value"] == 6

    def test_file_mode_invalid_output_fails(self):
        """Test FILE mode fails if any output item is invalid."""

        class ItemOutput(TypedDict):
            value: int

        @udf_tool(output_type=ItemOutput, granularity=Granularity.FILE)
        def batch_with_error(data):
            return [
                {"value": 1},
                {"wrong_field": "oops"},  # Invalid item
                {"value": 3},
            ]

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function("batch_with_error", [{"x": 1}, {"x": 2}, {"x": 3}])

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

        with pytest.raises(AgentActionsException) as exc_info:
            execute_user_defined_function("failing_function", {"text": "test"})

        error_msg = str(exc_info.value)
        assert "failing_function" in error_msg
        assert "Something went wrong" in error_msg

    def test_output_validation_error_includes_schema_info(self):
        """Test that output validation errors include schema information."""

        class RequiredOutput(TypedDict):
            required_field: str

        @udf_tool(output_type=RequiredOutput)
        def needs_field(data):
            return {"wrong_field": "value"}

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function("needs_field", {"data": "any"})

        error_msg = str(exc_info.value)
        assert "needs_field" in error_msg
        assert "validation failed" in error_msg.lower()
