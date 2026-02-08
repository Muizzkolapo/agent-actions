"""Integration tests for UDF type hint support.

Tests the full flow: register with output types -> compile -> execute -> validate output.
Note: Input validation is no longer performed - context_scope in workflow YAML defines input structure.
"""

import pytest
from typing import Dict, List, Optional, TypedDict

from agent_actions.utils.udf_management.registry import (
    udf_tool,
    clear_registry,
)
from agent_actions.utils.udf_management.tooling import execute_user_defined_function
from agent_actions.errors import SchemaValidationError
from agent_actions.utils.udf_management.type_conversion import clear_schema_cache


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry and schema cache before and after each test."""
    clear_registry()
    clear_schema_cache()
    yield
    clear_registry()
    clear_schema_cache()


class TestOutputValidation:
    """Tests for output schema validation."""

    def test_valid_output_passes(self):
        """Valid output should pass validation."""

        class Output(TypedDict):
            result: str

        @udf_tool(output_type=Output)
        def process(data):
            return {"result": "processed"}

        result = execute_user_defined_function("process", {"text": "hello"})
        assert result == {"result": "processed"}

    def test_invalid_output_raises(self):
        """Invalid output should raise SchemaValidationError."""

        class Output(TypedDict):
            result: str

        @udf_tool(output_type=Output)
        def bad_process(data):
            return {"wrong_field": "value"}  # Missing 'result' field

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function("bad_process", {"text": "hello"})

        assert "output" in str(exc_info.value).lower() or "result" in str(exc_info.value)

    def test_output_validation_disabled(self):
        """Output validation can be disabled."""

        class Output(TypedDict):
            result: str

        @udf_tool(output_type=Output)
        def process(data):
            return {"wrong": "output"}  # Would fail validation

        # Should not raise when validation is disabled
        result = execute_user_defined_function("process", {"text": "hello"}, validate_output=False)
        assert result == {"wrong": "output"}

    def test_no_output_schema_skips_validation(self):
        """Without output_type, output validation is skipped."""

        @udf_tool()  # No output_type
        def process(data):
            return {"anything": "goes"}

        # Should not raise - no output schema to validate against
        result = execute_user_defined_function("process", {"text": "hello"})
        assert result == {"anything": "goes"}


class TestComplexOutputTypes:
    """Tests for complex output type handling."""

    def test_list_field_in_output(self):
        """List[T] field in output should work."""

        class Output(TypedDict):
            items: List[str]

        @udf_tool(output_type=Output)
        def process(data):
            return {"items": ["a", "b", "c"]}

        result = execute_user_defined_function("process", {"x": 1})
        assert result == {"items": ["a", "b", "c"]}

    def test_optional_field_in_output(self):
        """Optional[T] field in output should not be required."""

        class Output(TypedDict):
            required: str
            optional: Optional[str]

        @udf_tool(output_type=Output)
        def process(data):
            return {"required": "value"}  # No optional field

        # Should work without optional field
        result = execute_user_defined_function("process", {"x": 1})
        assert result == {"required": "value"}

    def test_dict_field_in_output(self):
        """Dict[str, V] field in output should work."""

        class Output(TypedDict):
            metadata: Dict[str, int]

        @udf_tool(output_type=Output)
        def process(data):
            return {"metadata": {"a": 1, "b": 2}}

        result = execute_user_defined_function("process", {"x": 1})
        assert result == {"metadata": {"a": 1, "b": 2}}

    def test_nested_typeddict_in_output(self):
        """Nested TypedDict in output should work."""

        class Inner(TypedDict):
            value: int

        class Outer(TypedDict):
            inner: Inner

        @udf_tool(output_type=Outer)
        def process(data):
            return {"inner": {"value": 42}}

        result = execute_user_defined_function("process", {"x": 1})
        assert result == {"inner": {"value": 42}}
