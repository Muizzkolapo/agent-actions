"""Integration tests for UDF discovery and execution."""

import pytest
from pathlib import Path
import tempfile
import shutil

from agent_actions.core.udf_loader import discover_udfs, validate_udf_references
from agent_actions.core.udf_registry import clear_registry, UDF_REGISTRY
from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.core.exceptions import (
    DuplicateFunctionError,
    FunctionNotFoundError
)


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry before and after each test for isolation."""
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def temp_user_code_dir():
    """Create a temporary directory for user code."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    # Cleanup
    shutil.rmtree(temp_dir)


class TestUDFDiscoveryIntegration:
    """Integration tests for UDF discovery and execution workflow."""

    def test_full_workflow_with_udf_discovery(self, temp_user_code_dir):
        """Test end-to-end workflow: discover UDF, validate config, execute."""
        # 1. Create UDF file
        udf_file = temp_user_code_dir / "my_functions.py"
        udf_file.write_text("""
from agent_actions import udf_tool
import json

@udf_tool
def process_data(data):
    '''Process incoming data and add processed field.'''
    result = data.copy()
    result['processed'] = True
    return json.dumps(result)
""")

        # 2. Discover UDFs
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 1
        assert 'process_data' in registry

        # 3. Validate config references
        config = {
            'actions': [
                {'name': 'processor', 'impl': 'process_data'}
            ]
        }
        validate_udf_references(config)  # Should not raise

        # 4. Execute UDF via tooling
        input_data = {'id': 1, 'value': 'test'}
        result = execute_user_defined_function('process_data', input_data)

        import json
        parsed_result = json.loads(result)
        assert parsed_result['id'] == 1
        assert parsed_result['value'] == 'test'
        assert parsed_result['processed'] is True

    def test_discovery_with_multiple_modules(self, temp_user_code_dir):
        """Test discovery across multiple Python modules in different directories."""
        # Create nested structure
        validators_dir = temp_user_code_dir / "validators"
        validators_dir.mkdir()

        transformers_dir = temp_user_code_dir / "transformers"
        transformers_dir.mkdir()

        # Create UDF in validators
        validator_file = validators_dir / "data_validators.py"
        validator_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def validate_email(data):
    return '@' in data.get('email', '')
""")

        # Create UDF in transformers
        transformer_file = transformers_dir / "data_transformers.py"
        transformer_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def uppercase_name(data):
    result = data.copy()
    result['name'] = data.get('name', '').upper()
    return result
""")

        # Discover all UDFs
        registry = discover_udfs(temp_user_code_dir)

        assert len(registry) == 2
        assert 'validate_email' in registry
        assert 'uppercase_name' in registry

        # Execute both UDFs
        email_result = execute_user_defined_function('validate_email', {'email': 'test@example.com'})
        assert email_result is True

        name_result = execute_user_defined_function('uppercase_name', {'name': 'john'})
        assert name_result['name'] == 'JOHN'

    def test_discovery_validation_failure(self, temp_user_code_dir):
        """Test that validation fails when UDF not found in registry."""
        # Create UDF
        udf_file = temp_user_code_dir / "functions.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def existing_func():
    return "exists"
""")

        # Discover UDFs
        discover_udfs(temp_user_code_dir)

        # Config references non-existent function
        config = {
            'actions': [
                {'impl': 'existing_func'},  # This one exists
                {'impl': 'nonexistent_func'}  # This one doesn't
            ]
        }

        # Validation should fail
        with pytest.raises(FunctionNotFoundError) as exc_info:
            validate_udf_references(config)

        error = exc_info.value
        assert error.context['function_name'] == 'nonexistent_func'
        assert 'existing_func' in error.context['available_functions']

    def test_discovery_duplicate_detection(self, temp_user_code_dir):
        """Test duplicate UDF detection during discovery."""
        # Create two modules with same function name
        file1 = temp_user_code_dir / "module1.py"
        file1.write_text("""
from agent_actions import udf_tool

@udf_tool
def duplicate_func():
    return "module1"
""")

        file2 = temp_user_code_dir / "module2.py"
        file2.write_text("""
from agent_actions import udf_tool

@udf_tool
def duplicate_func():
    return "module2"
""")

        # Discovery should fail with duplicate error
        with pytest.raises(DuplicateFunctionError) as exc_info:
            discover_udfs(temp_user_code_dir)

        error = exc_info.value
        assert error.context['function_name'] == 'duplicate_func'
        assert 'module1.py' in error.context['existing_file'] or 'module2.py' in error.context['existing_file']

    def test_tooling_integration(self, temp_user_code_dir):
        """Test UDF execution via tool vendor integration."""
        # Create UDF that processes data
        udf_file = temp_user_code_dir / "tools.py"
        udf_file.write_text("""
from agent_actions import udf_tool
import json

@udf_tool
def enrich_data(data, **kwargs):
    '''Enrich data with additional fields.'''
    result = data.copy() if isinstance(data, dict) else {}

    # Add enrichment fields
    result['enriched'] = True
    result['version'] = kwargs.get('version', '1.0')

    return json.dumps(result)
""")

        # Discover UDFs
        registry = discover_udfs(temp_user_code_dir)
        assert 'enrich_data' in registry

        # Execute with additional kwargs
        input_data = {'id': 123, 'name': 'Test'}
        result = execute_user_defined_function(
            'enrich_data',
            input_data,
            version='2.0'
        )

        import json
        parsed = json.loads(result)
        assert parsed['id'] == 123
        assert parsed['name'] == 'Test'
        assert parsed['enriched'] is True
        assert parsed['version'] == '2.0'

    def test_case_insensitive_execution(self, temp_user_code_dir):
        """Test that UDF execution is case-insensitive."""
        # Create UDF with mixed case name
        udf_file = temp_user_code_dir / "functions.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def MyMixedCaseFunction(data):
    return "success"
""")

        # Discover UDFs
        discover_udfs(temp_user_code_dir)

        # Execute with different case variations
        result1 = execute_user_defined_function('MyMixedCaseFunction', {})
        result2 = execute_user_defined_function('mymixedcasefunction', {})
        result3 = execute_user_defined_function('MYMIXEDCASEFUNCTION', {})

        assert result1 == "success"
        assert result2 == "success"
        assert result3 == "success"

    def test_discovery_with_complex_imports(self, temp_user_code_dir):
        """Test discovery works with UDFs that have complex import statements."""
        # Create UDF with various imports
        udf_file = temp_user_code_dir / "complex_udf.py"
        udf_file.write_text("""
from agent_actions import udf_tool
import json
from pathlib import Path
from typing import Dict, Any

@udf_tool
def complex_processor(data: Dict[str, Any]) -> str:
    '''UDF with type hints and complex imports.'''
    processed = {
        'original': data,
        'processed_at': 'now',
        'type': 'complex'
    }
    return json.dumps(processed)
""")

        # Discover should handle complex imports
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 1
        assert 'complex_processor' in registry

        # Execute
        result = execute_user_defined_function('complex_processor', {'test': 'data'})

        import json
        parsed = json.loads(result)
        assert parsed['original'] == {'test': 'data'}
        assert parsed['type'] == 'complex'
