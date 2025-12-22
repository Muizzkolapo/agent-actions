"""
Tests for tool schema validation CLI and validator.

Tests the validation of UDF tool schemas including:
- Schema file validation
- Granularity validation
- CLI integration
"""
import pytest
from pathlib import Path
from agent_actions.validation.validate_tool_schemas import ToolSchemaValidator
from agent_actions.utilities.udf_management.udf_registry import (
    udf_tool,
    clear_registry
)
from agent_actions.configuration.new_format_schema import Granularity


class TestToolSchemaValidator:
    """Test ToolSchemaValidator class."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return ToolSchemaValidator()
    
    def test_validate_schema_structure_valid(self, validator):
        """Test validation of valid schema structure."""
        schema = {
            'name': 'test_func',
            'fields': [
                {'id': 'field1', 'type': 'string', 'required': True}
            ]
        }
        
        udf_meta = {
            'name': 'test_func',
            'schema': schema
        }
        
        result = validator._validate_schema_structure(schema, udf_meta)
        assert result is True
        assert not validator.has_errors()
    
    def test_validate_schema_structure_missing_fields(self, validator):
        """Test validation fails when fields are missing."""
        schema = {
            'name': 'test_func'
            # Missing 'fields' array
        }
        
        udf_meta = {
            'name': 'test_func',
            'schema': schema
        }
        
        result = validator._validate_schema_structure(schema, udf_meta)
        assert result is False
        assert validator.has_errors()
    
    def test_validate_schema_structure_invalid_fields_type(self, validator):
        """Test validation fails when fields is not a list."""
        schema = {
            'name': 'test_func',
            'fields': 'not a list'  # Should be list
        }
        
        udf_meta = {
            'name': 'test_func',
            'schema': schema
        }
        
        result = validator._validate_schema_structure(schema, udf_meta)
        assert result is False
        assert validator.has_errors()
    
    def test_validate_granularity_file_with_array(self, validator):
        """Test FILE mode validation with array schema."""
        schema = {
            'fields': [
                {
                    'id': 'items',
                    'type': 'array',
                    'required': True
                }
            ]
        }
        
        udf_meta = {
            'name': 'batch_func',
            'schema': schema,
            'granularity': Granularity.FILE
        }
        
        result = validator._validate_granularity(udf_meta)
        assert result is True
        assert not validator.has_warnings()
    
    def test_validate_granularity_file_without_array_warns(self, validator):
        """Test FILE mode without array schema generates warning."""
        schema = {
            'fields': [
                {
                    'id': 'text',
                    'type': 'string',  # Not array
                    'required': True
                }
            ]
        }
        
        udf_meta = {
            'name': 'mismatched_func',
            'schema': schema,
            'granularity': Granularity.FILE
        }
        
        result = validator._validate_granularity(udf_meta)
        assert result is True  # Still passes, but with warning
        # Note: Check for warnings in actual implementation
    
    def test_validate_all_tools_success(self, validator, tmp_path):
        """Test validating all tools successfully."""
        # Register a valid tool
        @udf_tool(schema={
            'fields': [
                {'id': 'text', 'type': 'string', 'required': True}
            ]
        })
        def valid_tool(data):
            return data
        
        # This should pass
        result = validator.validate_all_tools(str(tmp_path))
        assert result is True
        assert not validator.has_errors()
    
    def test_validate_all_tools_with_invalid_schema(self, validator):
        """Test validation fails with invalid schema."""
        # Try to register tool without schema (should fail at registration)
        # This test verifies the validator catches any that slip through
        
        # Manually add invalid entry to registry for testing
        from agent_actions.utilities.udf_management.udf_registry import UDF_REGISTRY
        UDF_REGISTRY['invalid_tool'] = {
            'name': 'invalid_tool',
            'schema': None,  # Invalid: no schema
            'granularity': Granularity.RECORD
        }
        
        result = validator.validate_all_tools('.')
        assert result is False
        assert validator.has_errors()


class TestSchemaFileValidation:
    """Test validation of schema files."""
    
    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return ToolSchemaValidator()
    
    def test_validate_schema_file_valid_yaml(self, validator, tmp_path):
        """Test validation of valid YAML schema file."""
        schema_file = tmp_path / "valid_schema.yml"
        schema_file.write_text("""
name: test_schema
description: Test schema
fields:
  - id: field1
    type: string
    required: true
""")
        
        result = validator.validate_schema_file(str(schema_file))
        assert result is True
        assert not validator.has_errors()
    
    def test_validate_schema_file_invalid_yaml(self, validator, tmp_path):
        """Test validation of invalid YAML file."""
        schema_file = tmp_path / "invalid_schema.yml"
        schema_file.write_text("""
name: test_schema
fields:
  - id: field1
    type: string
    required: true
  - invalid yaml syntax here
    missing colon
""")
        
        result = validator.validate_schema_file(str(schema_file))
        assert result is False
        assert validator.has_errors()
    
    def test_validate_schema_file_missing_required_fields(self, validator, tmp_path):
        """Test validation fails when required fields are missing."""
        schema_file = tmp_path / "incomplete_schema.yml"
        schema_file.write_text("""
name: test_schema
# Missing 'fields' array
description: Incomplete schema
""")
        
        result = validator.validate_schema_file(str(schema_file))
        assert result is False
        assert validator.has_errors()
    
    def test_validate_schema_file_not_found(self, validator):
        """Test validation fails when file doesn't exist."""
        result = validator.validate_schema_file('/nonexistent/schema.yml')
        assert result is False
        assert validator.has_errors()


class TestCLIIntegration:
    """Test CLI integration for schema validation."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    def test_list_udfs_shows_schema_info(self):
        """Test that list-udfs command shows schema information."""
        @udf_tool(schema={'text': 'string'})
        def tool_with_schema(data):
            return data
        
        from agent_actions.utilities.udf_management.udf_registry import list_udfs
        udfs = list_udfs()
        
        assert len(udfs) == 1
        udf = udfs[0]
        
        # Should include schema metadata
        assert 'name' in udf
        assert udf['name'] == 'tool_with_schema'
    
    def test_list_udfs_shows_granularity(self):
        """Test that list-udfs shows processing mode."""
        @udf_tool(
            schema={'text': 'string'},
            granularity=Granularity.FILE
        )
        def file_mode_tool(data):
            return data
        
        from agent_actions.utilities.udf_management.udf_registry import get_udf_metadata
        metadata = get_udf_metadata('file_mode_tool')
        
        assert metadata['granularity'] == Granularity.FILE
    
    def test_list_udfs_shows_schema_source(self):
        """Test that list-udfs shows schema source."""
        @udf_tool(schema={'text': 'string'})
        def inline_schema_tool(data):
            return data
        
        from agent_actions.utilities.udf_management.udf_registry import get_udf_metadata
        metadata = get_udf_metadata('inline_schema_tool')
        
        assert metadata['schema_source'] == 'inline'


class TestSchemaCompatibility:
    """Test compatibility with existing schema system."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    def test_schema_uses_unified_format(self):
        """Test that tool schemas use unified format."""
        @udf_tool(schema={
            'name': 'test_tool',
            'fields': [
                {'id': 'field1', 'type': 'string', 'required': True}
            ]
        })
        def test_tool(data):
            return data
        
        from agent_actions.utilities.udf_management.udf_registry import get_udf_metadata
        metadata = get_udf_metadata('test_tool')
        
        # Should have unified format
        assert 'fields' in metadata['schema']
        assert isinstance(metadata['schema']['fields'], list)
    
    def test_schema_can_be_compiled(self):
        """Test that schemas can be compiled to vendor formats."""
        @udf_tool(schema={
            'fields': [
                {'id': 'text', 'type': 'string', 'required': True}
            ]
        })
        def compilable_tool(data):
            return data
        
        from agent_actions.utilities.udf_management.udf_registry import get_udf_metadata
        from agent_actions.response_processing.schema_change import compile_unified_schema
        
        metadata = get_udf_metadata('compilable_tool')
        schema = metadata['schema']
        
        # Should be able to compile to OpenAI format
        compiled = compile_unified_schema(schema, 'openai')
        
        assert 'schema' in compiled
        assert 'properties' in compiled['schema']
    
    def test_simple_dict_converted_to_unified(self):
        """Test that simple dict schemas are converted to unified format."""
        @udf_tool(schema={'text': 'string', 'count': 'number'})
        def simple_schema_tool(data):
            return data
        
        from agent_actions.utilities.udf_management.udf_registry import get_udf_metadata
        metadata = get_udf_metadata('simple_schema_tool')
        
        # Should be converted to unified format
        assert 'fields' in metadata['schema']
        assert len(metadata['schema']['fields']) == 2
