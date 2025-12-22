"""
Unit tests for UDF schema requirements.

Tests the @udf_tool decorator with required schemas, including:
- Schema requirement enforcement
- Inline schema validation
- File-based schema loading
- Granularity specification (RECORD/FILE)
"""
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
from agent_actions.utilities.udf_management.udf_registry import (
    udf_tool,
    clear_registry,
    get_udf_metadata,
    UDF_REGISTRY
)
from agent_actions.configuration.new_format_schema import Granularity
from agent_actions.errors import ConfigurationError, DuplicateFunctionError


class TestSchemaRequirement:
    """Test that schemas are required for UDF registration."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    def test_decorator_without_schema_raises_error(self):
        """Test that @udf_tool without schema raises ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            @udf_tool
            def missing_schema(data):
                return data
        
        assert "must have a schema" in str(exc_info.value).lower()
        assert "missing_schema" in str(exc_info.value)
    
    def test_decorator_with_none_schema_raises_error(self):
        """Test that explicitly passing schema=None raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            @udf_tool(schema=None)
            def explicit_none(data):
                return data
        
        assert "must have a schema" in str(exc_info.value).lower()
    
    def test_decorator_with_both_none_raises_error(self):
        """Test that schema=None and schema_file=None raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            @udf_tool(schema=None, schema_file=None)
            def both_none(data):
                return data
        
        assert "must have a schema" in str(exc_info.value).lower()


class TestInlineSchema:
    """Test inline schema validation and registration."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    def test_simple_inline_schema_dict(self):
        """Test registration with simple dict schema (auto-converted to unified)."""
        @udf_tool(schema={'text': 'string', 'count': 'number'})
        def simple_transform(data):
            return data
        
        # Verify registration
        assert 'simple_transform' in UDF_REGISTRY
        metadata = get_udf_metadata('simple_transform')
        
        # Verify schema was converted to unified format
        assert 'fields' in metadata['schema']
        assert len(metadata['schema']['fields']) == 2
        assert metadata['schema']['name'] == 'simple_transform'
    
    def test_unified_format_inline_schema(self):
        """Test registration with unified format schema."""
        schema = {
            'name': 'process_user',
            'description': 'Process user data',
            'fields': [
                {'id': 'user_id', 'type': 'string', 'required': True},
                {'id': 'email', 'type': 'string', 'required': True},
                {'id': 'age', 'type': 'number', 'required': False}
            ]
        }
        
        @udf_tool(schema=schema)
        def process_user(data):
            return data
        
        metadata = get_udf_metadata('process_user')
        assert metadata['schema'] == schema
        assert metadata['schema_source'] == 'inline'
    
    def test_inline_schema_with_array_field(self):
        """Test inline schema with array field."""
        schema = {
            'fields': [
                {
                    'id': 'tags',
                    'type': 'array',
                    'required': True,
                    'items': {'type': 'string'}
                }
            ]
        }
        
        @udf_tool(schema=schema)
        def process_tags(data):
            return data
        
        metadata = get_udf_metadata('process_tags')
        assert metadata['schema']['fields'][0]['type'] == 'array'
        assert metadata['schema']['fields'][0]['items'] == {'type': 'string'}
    
    def test_inline_schema_with_nested_object(self):
        """Test inline schema with nested object."""
        schema = {
            'fields': [
                {
                    'id': 'user',
                    'type': 'object',
                    'required': True,
                    'description': 'User information'
                },
                {
                    'id': 'settings',
                    'type': 'object',
                    'required': False,
                    'description': 'User settings'
                }
            ]
        }
        
        @udf_tool(schema=schema)
        def process_profile(data):
            return data
        
        metadata = get_udf_metadata('process_profile')
        assert len(metadata['schema']['fields']) == 2
        assert metadata['schema']['fields'][0]['type'] == 'object'
    
    def test_invalid_schema_type_raises_error(self):
        """Test that non-dict schema raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            @udf_tool(schema="invalid")
            def bad_schema(data):
                return data
        
        assert "must be a dictionary" in str(exc_info.value).lower()
    
    def test_required_field_notation(self):
        """Test required field notation with '!' suffix."""
        schema = {
            'user_id': 'string!',  # Required
            'email': 'string',     # Optional
        }
        
        @udf_tool(schema=schema)
        def check_required(data):
            return data
        
        metadata = get_udf_metadata('check_required')
        fields = metadata['schema']['fields']
        
        # Find user_id field
        user_id_field = next(f for f in fields if f['id'] == 'user_id')
        email_field = next(f for f in fields if f['id'] == 'email')
        
        assert user_id_field['required'] is True
        assert email_field['required'] is False


class TestFileBasedSchema:
    """Test file-based schema loading."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    def test_schema_file_loading(self, tmp_path):
        """Test loading schema from YAML file."""
        # Create schema file
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        schema_file = schema_dir / "process_user.yml"
        
        schema_content = """
name: process_user
description: Process user data
fields:
  - id: user_id
    type: string
    required: true
  - id: email
    type: string
    required: true
"""
        schema_file.write_text(schema_content)
        
        # Create tool file in same directory
        tool_file = tmp_path / "tool.py"
        
        # Mock the schema loading
        with patch('agent_actions.utilities.udf_management.udf_registry.inspect.getfile') as mock_getfile:
            mock_getfile.return_value = str(tool_file)
            
            with patch('agent_actions.utilities.udf_management.udf_registry.SchemaLoader.load_schema') as mock_load:
                mock_load.return_value = {
                    'name': 'process_user',
                    'description': 'Process user data',
                    'fields': [
                        {'id': 'user_id', 'type': 'string', 'required': True},
                        {'id': 'email', 'type': 'string', 'required': True}
                    ]
                }
                
                @udf_tool(schema_file='schemas/process_user.yml')
                def process_user(data):
                    return data
                
                metadata = get_udf_metadata('process_user')
                assert metadata['schema_source'] == 'file'
                assert metadata['schema_file'] == 'schemas/process_user.yml'
                assert metadata['schema']['name'] == 'process_user'
    
    def test_missing_schema_file_raises_error(self, tmp_path):
        """Test that missing schema file raises ConfigurationError."""
        tool_file = tmp_path / "tool.py"
        
        with patch('agent_actions.utilities.udf_management.udf_registry.inspect.getfile') as mock_getfile:
            mock_getfile.return_value = str(tool_file)
            
            with pytest.raises(ConfigurationError) as exc_info:
                @udf_tool(schema_file='missing.yml')
                def missing_file(data):
                    return data
            
            assert "not found" in str(exc_info.value).lower()
            assert "missing.yml" in str(exc_info.value)


class TestGranularity:
    """Test processing mode specification."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    def test_default_granularity_is_record(self):
        """Test that default processing mode is RECORD."""
        @udf_tool(schema={'text': 'string'})
        def default_mode(data):
            return data
        
        metadata = get_udf_metadata('default_mode')
        assert metadata['granularity'] == Granularity.RECORD
    
    def test_explicit_record_mode(self):
        """Test explicit RECORD mode specification."""
        @udf_tool(
            schema={'text': 'string'},
            granularity=Granularity.RECORD
        )
        def record_mode(data):
            return data
        
        metadata = get_udf_metadata('record_mode')
        assert metadata['granularity'] == Granularity.RECORD
    
    def test_file_mode_specification(self):
        """Test FILE mode specification."""
        schema = {
            'fields': [
                {
                    'id': 'items',
                    'type': 'array',
                    'required': True,
                    'items': {'type': 'object'}
                }
            ]
        }
        
        @udf_tool(
            schema=schema,
            granularity=Granularity.FILE
        )
        def file_mode(data):
            return [item for item in data]
        
        metadata = get_udf_metadata('file_mode')
        assert metadata['granularity'] == Granularity.FILE
    
    def test_granularity_stored_in_registry(self):
        """Test that processing mode is stored in registry."""
        @udf_tool(
            schema={'text': 'string'},
            granularity=Granularity.FILE
        )
        def check_storage(data):
            return data
        
        assert 'check_storage' in UDF_REGISTRY
        assert UDF_REGISTRY['check_storage']['granularity'] == Granularity.FILE


class TestSchemaMetadata:
    """Test schema metadata storage in registry."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    def test_metadata_includes_schema(self):
        """Test that metadata includes schema."""
        schema = {'text': 'string'}
        
        @udf_tool(schema=schema)
        def with_schema(data):
            return data
        
        metadata = get_udf_metadata('with_schema')
        assert 'schema' in metadata
        assert metadata['schema'] is not None
    
    def test_metadata_includes_schema_source(self):
        """Test that metadata includes schema source."""
        @udf_tool(schema={'text': 'string'})
        def inline_source(data):
            return data
        
        metadata = get_udf_metadata('inline_source')
        assert 'schema_source' in metadata
        assert metadata['schema_source'] in ['inline', 'file']
    
    def test_metadata_includes_granularity(self):
        """Test that metadata includes processing mode."""
        @udf_tool(schema={'text': 'string'})
        def with_mode(data):
            return data
        
        metadata = get_udf_metadata('with_mode')
        assert 'granularity' in metadata
        assert isinstance(metadata['granularity'], Granularity)
    
    def test_all_standard_metadata_present(self):
        """Test that all standard metadata fields are present."""
        @udf_tool(schema={'text': 'string'})
        def full_metadata(data):
            """Test function."""
            return data
        
        metadata = get_udf_metadata('full_metadata')
        
        # Standard fields
        assert 'function' in metadata
        assert 'module' in metadata
        assert 'name' in metadata
        assert 'file' in metadata
        assert 'docstring' in metadata
        assert 'signature' in metadata
        
        # New schema fields
        assert 'schema' in metadata
        assert 'schema_source' in metadata
        assert 'granularity' in metadata


class TestDuplicateDetection:
    """Test duplicate function detection with schemas."""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear registry before and after each test."""
        clear_registry()
        yield
        clear_registry()
    
    def test_duplicate_function_with_schema_raises_error(self):
        """Test that duplicate function names raise DuplicateFunctionError."""
        @udf_tool(schema={'text': 'string'})
        def duplicate_func(data):
            return data
        
        with pytest.raises(DuplicateFunctionError):
            @udf_tool(schema={'text': 'string'})
            def duplicate_func(data):  # Same name
                return data
    
    def test_case_insensitive_duplicate_detection(self):
        """Test that duplicate detection is case-insensitive."""
        @udf_tool(schema={'text': 'string'})
        def MyFunction(data):
            return data
        
        with pytest.raises(DuplicateFunctionError):
            @udf_tool(schema={'text': 'string'})
            def myfunction(data):  # Different case, same name
                return data
