"""Integration tests for UDF discovery and execution."""
import pytest
from pathlib import Path
import tempfile
import shutil
from agent_actions.input_loading.udf_loader import discover_udfs, validate_udf_references
from agent_actions.utilities.udf_registry import clear_registry, UDF_REGISTRY
from agent_actions.utilities.tooling import execute_user_defined_function
from agent_actions.errors import DuplicateFunctionError, FunctionNotFoundError  # New modular pattern!

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
    shutil.rmtree(temp_dir)

class TestUDFDiscoveryIntegration:
    """Integration tests for UDF discovery and execution workflow."""

    def test_full_workflow_with_udf_discovery(self, temp_user_code_dir):
        """Test end-to-end workflow: discover UDF, validate config, execute."""
        udf_file = temp_user_code_dir / 'my_functions.py'
        udf_file.write_text("\nfrom agent_actions import udf_tool\nimport json\n\n@udf_tool\ndef process_data(data):\n    '''Process incoming data and add processed field.'''\n    result = data.copy()\n    result['processed'] = True\n    return json.dumps(result)\n")
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 1
        assert 'process_data' in registry
        config = {'actions': [{'name': 'processor', 'impl': 'process_data'}]}
        validate_udf_references(config)
        input_data = {'id': 1, 'value': 'test'}
        result = execute_user_defined_function('process_data', input_data)
        import json
        parsed_result = json.loads(result)
        assert parsed_result['id'] == 1
        assert parsed_result['value'] == 'test'
        assert parsed_result['processed'] is True

    def test_discovery_with_multiple_modules(self, temp_user_code_dir):
        """Test discovery across multiple Python modules in different directories."""
        validators_dir = temp_user_code_dir / 'validators'
        validators_dir.mkdir()
        transformers_dir = temp_user_code_dir / 'transformers'
        transformers_dir.mkdir()
        validator_file = validators_dir / 'data_validators.py'
        validator_file.write_text("\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef validate_email(data):\n    return '@' in data.get('email', '')\n")
        transformer_file = transformers_dir / 'data_transformers.py'
        transformer_file.write_text("\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef uppercase_name(data):\n    result = data.copy()\n    result['name'] = data.get('name', '').upper()\n    return result\n")
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 2
        assert 'validate_email' in registry
        assert 'uppercase_name' in registry
        email_result = execute_user_defined_function('validate_email', {'email': 'test@example.com'})
        assert email_result is True
        name_result = execute_user_defined_function('uppercase_name', {'name': 'john'})
        assert name_result['name'] == 'JOHN'

    def test_discovery_validation_failure(self, temp_user_code_dir):
        """Test that validation fails when UDF not found in registry."""
        udf_file = temp_user_code_dir / 'functions.py'
        udf_file.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef existing_func():\n    return "exists"\n')
        discover_udfs(temp_user_code_dir)
        config = {'actions': [{'impl': 'existing_func'}, {'impl': 'nonexistent_func'}]}
        with pytest.raises(FunctionNotFoundError) as exc_info:
            validate_udf_references(config)
        error = exc_info.value
        assert error.context['function_name'] == 'nonexistent_func'
        assert 'existing_func' in error.context['available_functions']

    def test_discovery_duplicate_detection(self, temp_user_code_dir):
        """Test duplicate UDF detection during discovery."""
        file1 = temp_user_code_dir / 'module1.py'
        file1.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef duplicate_func():\n    return "module1"\n')
        file2 = temp_user_code_dir / 'module2.py'
        file2.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef duplicate_func():\n    return "module2"\n')
        with pytest.raises(DuplicateFunctionError) as exc_info:
            discover_udfs(temp_user_code_dir)
        error = exc_info.value
        assert error.context['function_name'] == 'duplicate_func'
        assert 'module1.py' in error.context['existing_file'] or 'module2.py' in error.context['existing_file']

    def test_tooling_integration(self, temp_user_code_dir):
        """Test UDF execution via tool vendor integration."""
        udf_file = temp_user_code_dir / 'tools.py'
        udf_file.write_text("\nfrom agent_actions import udf_tool\nimport json\n\n@udf_tool\ndef enrich_data(data, **kwargs):\n    '''Enrich data with additional fields.'''\n    result = data.copy() if isinstance(data, dict) else {}\n\n    # Add enrichment fields\n    result['enriched'] = True\n    result['version'] = kwargs.get('version', '1.0')\n\n    return json.dumps(result)\n")
        registry = discover_udfs(temp_user_code_dir)
        assert 'enrich_data' in registry
        input_data = {'id': 123, 'name': 'Test'}
        result = execute_user_defined_function('enrich_data', input_data, version='2.0')
        import json
        parsed = json.loads(result)
        assert parsed['id'] == 123
        assert parsed['name'] == 'Test'
        assert parsed['enriched'] is True
        assert parsed['version'] == '2.0'

    def test_case_insensitive_execution(self, temp_user_code_dir):
        """Test that UDF execution is case-insensitive."""
        udf_file = temp_user_code_dir / 'functions.py'
        udf_file.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef MyMixedCaseFunction(data):\n    return "success"\n')
        discover_udfs(temp_user_code_dir)
        result1 = execute_user_defined_function('MyMixedCaseFunction', {})
        result2 = execute_user_defined_function('mymixedcasefunction', {})
        result3 = execute_user_defined_function('MYMIXEDCASEFUNCTION', {})
        assert result1 == 'success'
        assert result2 == 'success'
        assert result3 == 'success'

    def test_discovery_with_complex_imports(self, temp_user_code_dir):
        """Test discovery works with UDFs that have complex import statements."""
        udf_file = temp_user_code_dir / 'complex_udf.py'
        udf_file.write_text("\nfrom agent_actions import udf_tool\nimport json\nfrom pathlib import Path\nfrom typing import Dict, Any\n\n@udf_tool\ndef complex_processor(data: Dict[str, Any]) -> str:\n    '''UDF with type hints and complex imports.'''\n    processed = {\n        'original': data,\n        'processed_at': 'now',\n        'type': 'complex'\n    }\n    return json.dumps(processed)\n")
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 1
        assert 'complex_processor' in registry
        result = execute_user_defined_function('complex_processor', {'test': 'data'})
        import json
        parsed = json.loads(result)
        assert parsed['original'] == {'test': 'data'}
        assert parsed['type'] == 'complex'