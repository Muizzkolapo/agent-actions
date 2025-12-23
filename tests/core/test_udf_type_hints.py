"""Integration tests for UDF type hint support.

Tests the full flow: register with types -> compile -> execute -> validate.
"""

import dataclasses
import pytest
from typing import Dict, List, Optional, TypedDict

from agent_actions.utilities.udf_management.udf_registry import (
    udf_tool, get_udf_metadata, clear_registry
)
from agent_actions.utilities.udf_management.tooling import execute_user_defined_function
from agent_actions.errors import SchemaValidationError
from agent_actions.utilities.udf_management.type_conversion import HAS_PYDANTIC, clear_schema_cache


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry and schema cache before and after each test."""
    clear_registry()
    clear_schema_cache()
    yield
    clear_registry()
    clear_schema_cache()


# =============================================================================
# Registration Tests
# =============================================================================

class TestTypeHintRegistration:
    """Tests for registering UDFs with type hints."""

    def test_register_with_input_type(self):
        """UDF with input_type should register successfully."""
        class Input(TypedDict):
            name: str
            age: int

        @udf_tool(input_type=Input)
        def process(data):
            return data

        metadata = get_udf_metadata('process')
        assert metadata['schema'] is not None
        assert metadata['schema']['name'] == 'Input'
        assert metadata['json_schema'] is not None

    def test_register_with_output_type(self):
        """UDF with output_type should store output schema."""
        class Input(TypedDict):
            text: str

        class Output(TypedDict):
            result: str

        @udf_tool(input_type=Input, output_type=Output)
        def process(data):
            return {'result': 'done'}

        metadata = get_udf_metadata('process')
        assert metadata['output_schema'] is not None
        assert metadata['output_schema']['name'] == 'Output'
        assert metadata['json_output_schema'] is not None

    def test_register_with_dataclass(self):
        """UDF with dataclass input_type should work."""
        @dataclasses.dataclass
        class Input:
            name: str
            count: int = 0

        @udf_tool(input_type=Input)
        def process(data):
            return data

        metadata = get_udf_metadata('process')
        fields = {f['id']: f for f in metadata['schema']['fields']}
        assert fields['name']['required'] is True
        assert fields['count']['required'] is False

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_register_with_pydantic(self):
        """UDF with Pydantic input_type should work."""
        from pydantic import BaseModel

        class Input(BaseModel):
            name: str
            count: int = 0

        @udf_tool(input_type=Input)
        def process(data):
            return data

        metadata = get_udf_metadata('process')
        fields = {f['id']: f for f in metadata['schema']['fields']}
        assert fields['name']['required'] is True
        assert fields['count']['required'] is False


# =============================================================================
# Execution Tests
# =============================================================================

class TestTypeHintExecution:
    """Tests for executing UDFs with type hints."""

    def test_execute_with_valid_input(self):
        """Valid input should pass validation."""
        class Input(TypedDict):
            name: str
            age: int

        @udf_tool(input_type=Input)
        def process(data):
            return {'status': 'ok', 'name': data['name']}

        result = execute_user_defined_function('process', {'name': 'Alice', 'age': 30})
        assert result == {'status': 'ok', 'name': 'Alice'}

    def test_execute_with_invalid_input(self):
        """Invalid input should raise SchemaValidationError."""
        class Input(TypedDict):
            name: str
            age: int

        @udf_tool(input_type=Input)
        def process(data):
            return data

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function('process', {'name': 'Alice'})  # missing age

        assert 'age' in str(exc_info.value) or 'required' in str(exc_info.value).lower()


# =============================================================================
# Output Validation Tests
# =============================================================================

class TestOutputValidation:
    """Tests for output schema validation."""

    def test_valid_output_passes(self):
        """Valid output should pass validation."""
        class Input(TypedDict):
            text: str

        class Output(TypedDict):
            result: str

        @udf_tool(input_type=Input, output_type=Output)
        def process(data):
            return {'result': 'processed'}

        result = execute_user_defined_function('process', {'text': 'hello'})
        assert result == {'result': 'processed'}

    def test_invalid_output_raises(self):
        """Invalid output should raise SchemaValidationError."""
        class Input(TypedDict):
            text: str

        class Output(TypedDict):
            result: str

        @udf_tool(input_type=Input, output_type=Output)
        def bad_process(data):
            return {'wrong_field': 'value'}  # Missing 'result' field

        with pytest.raises(SchemaValidationError) as exc_info:
            execute_user_defined_function('bad_process', {'text': 'hello'})

        assert 'output' in str(exc_info.value).lower() or 'result' in str(exc_info.value)

    def test_output_validation_disabled(self):
        """Output validation can be disabled."""
        class Input(TypedDict):
            text: str

        class Output(TypedDict):
            result: str

        @udf_tool(input_type=Input, output_type=Output)
        def process(data):
            return {'wrong': 'output'}  # Would fail validation

        # Should not raise when validation is disabled
        result = execute_user_defined_function(
            'process', {'text': 'hello'}, validate_output=False
        )
        assert result == {'wrong': 'output'}

    def test_no_output_schema_skips_validation(self):
        """Without output_type, output validation is skipped."""
        class Input(TypedDict):
            text: str

        @udf_tool(input_type=Input)  # No output_type
        def process(data):
            return {'anything': 'goes'}

        # Should not raise - no output schema to validate against
        result = execute_user_defined_function('process', {'text': 'hello'})
        assert result == {'anything': 'goes'}


# =============================================================================
# Complex Type Tests
# =============================================================================

class TestComplexTypes:
    """Tests for complex type handling."""

    def test_list_field(self):
        """List[T] field should work."""
        class Input(TypedDict):
            items: List[str]

        @udf_tool(input_type=Input)
        def process(data):
            return {'count': len(data['items'])}

        result = execute_user_defined_function('process', {'items': ['a', 'b', 'c']})
        assert result == {'count': 3}

    def test_optional_field(self):
        """Optional[T] field should not be required."""
        class Input(TypedDict):
            required: str
            optional: Optional[str]

        @udf_tool(input_type=Input)
        def process(data):
            return data

        # Should work without optional field
        result = execute_user_defined_function('process', {'required': 'value'})
        assert result == {'required': 'value'}

    def test_dict_field(self):
        """Dict[str, V] field should work."""
        class Input(TypedDict):
            metadata: Dict[str, int]

        @udf_tool(input_type=Input)
        def process(data):
            return {'total': sum(data['metadata'].values())}

        result = execute_user_defined_function(
            'process', {'metadata': {'a': 1, 'b': 2}}
        )
        assert result == {'total': 3}

    def test_nested_typeddict(self):
        """Nested TypedDict should work."""
        class Inner(TypedDict):
            value: int

        class Outer(TypedDict):
            inner: Inner

        @udf_tool(input_type=Outer)
        def process(data):
            return {'doubled': data['inner']['value'] * 2}

        result = execute_user_defined_function('process', {'inner': {'value': 21}})
        assert result == {'doubled': 42}
