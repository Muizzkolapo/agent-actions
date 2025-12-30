"""
Integration tests for UDF schema validation and execution.

Tests end-to-end UDF execution with schema validation, including:
- Input validation against schemas
- Granularity enforcement (RECORD/FILE)
- Error handling and messages
"""

import pytest
from typing import List, Optional, TypedDict
from agent_actions.utilities.udf_management.udf_registry import udf_tool, clear_registry
from agent_actions.configuration.new_format_schema import Granularity
from agent_actions.utilities.udf_management.tooling import execute_user_defined_function
from agent_actions.errors import SchemaValidationError, AgentActionsException


class TestSchemaValidation:
    """Test schema validation during UDF execution."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()

    def test_valid_input_passes_validation(self):
        """Test that valid input passes schema validation."""

        class TransformInput(TypedDict):
            text: str

        @udf_tool(input_type=TransformInput)
        def transform_text(data):
            return {"result": data["text"].upper()}

        result = execute_user_defined_function("transform_text", {"text": "hello world"})

        assert result == {"result": "HELLO WORLD"}

    def test_missing_required_field_fails_validation(self):
        """Test that missing required field fails validation."""

        class UserInput(TypedDict):
            user_id: str
            email: str

        @udf_tool(input_type=UserInput)
        def process_user(data):
            return data

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "process_user",
                {"user_id": "123"},  # Missing email
            )

        assert "validation failed" in str(exc_info.value).lower()

    def test_wrong_type_fails_validation(self):
        """Test that wrong type fails validation."""

        class AgeInput(TypedDict):
            age: int

        @udf_tool(input_type=AgeInput)
        def check_age(data):
            return data

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "check_age",
                {"age": "not a number"},  # Wrong type
            )

        assert "validation failed" in str(exc_info.value).lower()

    def test_optional_field_can_be_missing(self):
        """Test that optional fields can be omitted."""

        class NameInput(TypedDict):
            name: str
            nickname: Optional[str]

        @udf_tool(input_type=NameInput)
        def process_name(data):
            return {"name": data["name"], "nickname": data.get("nickname", "N/A")}

        result = execute_user_defined_function(
            "process_name",
            {"name": "John"},  # nickname is optional
        )

        assert result["name"] == "John"
        assert result["nickname"] == "N/A"

    def test_validation_can_be_disabled(self):
        """Test that validation can be disabled."""

        class TextInput(TypedDict):
            text: str

        @udf_tool(input_type=TextInput)
        def no_validation(data):
            return data

        # Should not raise even with invalid input when validation disabled
        result = execute_user_defined_function(
            "no_validation", {"wrong_field": "value"}, validate_input=False
        )

        assert result == {"wrong_field": "value"}


class TestGranularityEnforcement:
    """Test processing mode enforcement during execution."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()

    def test_record_mode_expects_dict_input(self):
        """Test that RECORD mode expects dict input."""

        class RecordInput(TypedDict):
            text: str

        @udf_tool(input_type=RecordInput, granularity=Granularity.RECORD)
        def record_processor(data):
            return data

        # Valid: dict input
        result = execute_user_defined_function("record_processor", {"text": "hello"})
        assert result == {"text": "hello"}

    def test_record_mode_rejects_array_input(self):
        """Test that RECORD mode rejects array input."""

        class RecordInput(TypedDict):
            text: str

        @udf_tool(input_type=RecordInput, granularity=Granularity.RECORD)
        def record_only(data):
            return data

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "record_only",
                [{"text": "hello"}, {"text": "world"}],  # Array not allowed
            )

        assert "expects object input" in str(exc_info.value).lower()
        assert "RECORD" in str(exc_info.value)

    def test_file_mode_expects_array_input(self):
        """Test that FILE mode expects array input."""

        class FileItem(TypedDict):
            id: int

        @udf_tool(input_type=FileItem, granularity=Granularity.FILE)
        def file_processor(data):
            return [item for item in data]

        # Valid: array input
        result = execute_user_defined_function("file_processor", [{"id": 1}, {"id": 2}])
        assert len(result) == 2

    def test_file_mode_rejects_dict_input(self):
        """Test that FILE mode rejects dict input."""

        class FileItem(TypedDict):
            id: int

        @udf_tool(input_type=FileItem, granularity=Granularity.FILE)
        def file_only(data):
            return data

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function(
                "file_only",
                {"id": 1},  # Dict not allowed in FILE mode
            )

        assert "expects array input" in str(exc_info.value).lower()
        assert "FILE" in str(exc_info.value)


class TestEndToEndExecution:
    """Test end-to-end UDF execution with various schemas."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()

    def test_simple_transform_with_validation(self):
        """Test simple data transformation with validation."""

        class TextInput(TypedDict):
            text: str

        @udf_tool(input_type=TextInput)
        def uppercase_transform(data):
            return {"text": data["text"].upper()}

        result = execute_user_defined_function("uppercase_transform", {"text": "hello"})

        assert result["text"] == "HELLO"

    def test_complex_object_processing(self):
        """Test processing complex nested objects."""

        class ProfileInput(TypedDict):
            user: dict
            preferences: Optional[dict]

        @udf_tool(input_type=ProfileInput)
        def process_user_profile(data):
            user = data["user"]
            prefs = data.get("preferences", {})

            return {"user_id": user.get("id"), "theme": prefs.get("theme", "default")}

        result = execute_user_defined_function(
            "process_user_profile",
            {"user": {"id": "123", "name": "John"}, "preferences": {"theme": "dark"}},
        )

        assert result["user_id"] == "123"
        assert result["theme"] == "dark"

    def test_array_field_processing(self):
        """Test processing array fields."""

        class TagsInput(TypedDict):
            tags: List[str]

        @udf_tool(input_type=TagsInput)
        def process_tags(data):
            return {"tags": [tag.upper() for tag in data["tags"]], "count": len(data["tags"])}

        result = execute_user_defined_function(
            "process_tags", {"tags": ["python", "testing", "tdd"]}
        )

        assert result["tags"] == ["PYTHON", "TESTING", "TDD"]
        assert result["count"] == 3

    def test_batch_processing_file_mode(self):
        """Test batch processing in FILE mode."""

        class BatchItem(TypedDict):
            value: int

        @udf_tool(input_type=BatchItem, granularity=Granularity.FILE)
        def batch_multiply(data):
            return [{"value": item["value"] * 2} for item in data]

        result = execute_user_defined_function(
            "batch_multiply", [{"value": 1}, {"value": 2}, {"value": 3}]
        )

        assert len(result) == 3
        assert result[0]["value"] == 2
        assert result[1]["value"] == 4
        assert result[2]["value"] == 6


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

        class TextInput(TypedDict):
            text: str

        @udf_tool(input_type=TextInput)
        def failing_function(data):
            raise ValueError("Something went wrong")

        with pytest.raises(AgentActionsException) as exc_info:
            execute_user_defined_function("failing_function", {"text": "test"})

        error_msg = str(exc_info.value)
        assert "failing_function" in error_msg
        assert "Something went wrong" in error_msg

    def test_validation_error_includes_schema_info(self):
        """Test that validation errors include schema information."""

        class RequiredInput(TypedDict):
            required_field: str

        @udf_tool(input_type=RequiredInput)
        def needs_field(data):
            return data

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function("needs_field", {"wrong_field": "value"})

        error_msg = str(exc_info.value)
        assert "needs_field" in error_msg
        assert "validation failed" in error_msg.lower()

    def test_granularity_error_is_clear(self):
        """Test that processing mode errors are clear."""

        class RecordInput(TypedDict):
            text: str

        @udf_tool(input_type=RecordInput, granularity=Granularity.RECORD)
        def record_func(data):
            return data

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function("record_func", ["array", "input"])

        error_msg = str(exc_info.value)
        assert "RECORD" in error_msg
        assert "expects object input" in error_msg.lower()


class TestSchemaIntegrationWithExistingSystem:
    """Test integration with existing schema system."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()

    def test_unified_format_compatibility(self):
        """Test that schemas use unified format compatible with existing system."""

        class TestInput(TypedDict):
            field1: str

        @udf_tool(input_type=TestInput)
        def test_func(data):
            return data

        from agent_actions.utilities.udf_management.udf_registry import get_udf_metadata

        metadata = get_udf_metadata("test_func")

        # Should have unified format
        assert "fields" in metadata["schema"]
        assert isinstance(metadata["schema"]["fields"], list)

    def test_schema_compilation_for_validation(self):
        """Test that schemas can be compiled for validation."""

        class CompilableInput(TypedDict):
            text: str

        @udf_tool(input_type=CompilableInput)
        def compilable_schema(data):
            return data

        # This should work without errors
        result = execute_user_defined_function(
            "compilable_schema", {"text": "test"}, validate_input=True
        )

        assert result == {"text": "test"}
