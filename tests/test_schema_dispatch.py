import pytest
from unittest.mock import MagicMock, patch
from agent_actions.response_processing.schema_change import prepare_schema_unified
from agent_actions.response_processing.config_schema import AgentConfig

# Patch where it is USED, not where it is defined
@pytest.fixture
def mock_string_processor():
    with patch('agent_actions.prompt_generation.prompt_utils.StringProcessor') as mock:
        yield mock

@pytest.fixture
def mock_schema_loader():
    with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock:
        yield mock

def test_schema_dispatch_simple(mock_string_processor, mock_schema_loader):
    """Test that dispatch_task is replaced in a simple schema field."""
    # Setup mock return value
    mock_string_processor.call_user_function.return_value = ["a", "b", "c"]
    
    # Mock SchemaLoader to return a pre-constructed unified schema
    mock_schema_loader.load_schema.return_value = {
        'name': 'test_schema',
        'fields': [
            {
                'id': 'category',
                'type': 'string',
                'enum': "dispatch_task('get_categories')"
            }
        ]
    }
    
    # Config referring to that schema
    agent_config = {
        'schema_name': 'test_schema',
        'name': 'test_agent'
    }
    
    # Call prepare_schema
    schema, _ = prepare_schema_unified(
        agent_config, 
        vendor='openai',
        tools_path='/tmp/tools', # Dummy path 
        context_data={'data': 123}
    )
    
    # Verify StringProcessor was called
    mock_string_processor.call_user_function.assert_called_with('get_categories', '/tmp/tools', '{"data": 123}')
    
    # Verify schema structure (OpenAI format)
    assert schema['schema']['properties']['category']['enum'] == ["a", "b", "c"]

def test_schema_dispatch_captured_results(mock_string_processor, mock_schema_loader):
    """Test that results are captured when add_dispatch is True."""
    # Setup mock
    mock_string_processor.call_user_function.return_value = "dynamic_value"
    
    # Mock SchemaLoader
    mock_schema_loader.load_schema.return_value = {
        'name': 'test_schema',
        'fields': [
            {
                'id': 'field',
                'type': 'string',
                'description': "dispatch_task('get_value')"
            }
        ]
    }
    
    # Config with add_dispatch
    agent_config = {
        'schema_name': 'test_schema',
        'name': 'test_agent',
        'add_dispatch': True
    }
    
    # Call prepare_schema
    schema, captured_results = prepare_schema_unified(
        agent_config, 
        vendor='gemini',
        tools_path='/tmp/tools',
        context_data={}
    )
    
    # Verify captured results
    assert captured_results['get_value'] == "dynamic_value"

def test_schema_dispatch_recursive(mock_string_processor, mock_schema_loader):
    """Test recursive replacement in nested schema."""
    mock_string_processor.call_user_function.side_effect = lambda name, *args: f"resolved_{name}"
    
    mock_schema_loader.load_schema.return_value = {
        'name': 'nested_schema',
        'fields': [
            {
                'id': 'nested',
                'type': 'object',
                'items': { # Unified schema uses 'items' for object properties sometimes (legacy?) or just define structure directly
                    # Actually valid unified schema structure for object is complex, 
                    # let's use the passthrough dict approach which prepare_schema_unified supports for legacy
                    # But wait, prepare_schema_unified calls compile_unified_schema
                    # Let's mock a simple structure that supports arbitrary nesting if possible
                     'type': 'object',
                     'properties': {
                        'inner': "dispatch_task('func1')",
                        'list': ["dispatch_task('func2')", "static"]
                     }
                }
            }
        ]
    }
    
    # Wait, compile_unified_schema iterates 'fields'.
    # If type is object, it expects 'properties' in the target format compilation logic?
    # Let's look at compile_field in schema_change.py
    # if field['type'] == 'array' and 'items' in field: prop['items'] = field['items']
    # If I put properties inside 'items' (misuse) or just as extra keys?
    # compile_field passes through extra keys if I just rely on dict replacement.
    
    # Let's try to construct a schema that `compile_unified_schema` handles.
    # It converts fields -> properties.
    # If I have a field 'nested', it becomes a property 'nested'.
    # If I want nested properties, I should define the object structure.
    
    # Actually, let's just test `_inject_functions_into_schema` directly if possible?
    # No, we want to test integration.
    
    # Unified schema for object:
    mock_schema_loader.load_schema.return_value = {
        'name': 'nested_schema',
        'fields': [
            {
                'id': 'config',
                'type': 'object',
                'default': "dispatch_task('func1')", # String replacement
                'properties': { # Not standard unified field but maybe passed through?
                     'setting': "dispatch_task('func2')"
                }
            }
        ]
    }
    
    agent_config = {
        'schema_name': 'nested_schema',
        'name': 'test_agent'
    }
    
    # We need to ensure that the fields we put in actually get preserved in the output to be checked.
    # compile_field copies: title, description, pattern, minItems, maxItems.
    # It does NOT copy arbitrary keys like 'properties' unless it's an array 'items'.
    # EXCEPT: This test is about dispatch replacement happening BEFORE compilation.
    # So if I use a supported field like 'description', it should work.
    
    mock_schema_loader.load_schema.return_value = {
        'name': 'nested_schema',
        'fields': [
            {
                'id': 'field1',
                'type': 'string',
                'description': "dispatch_task('func1')"
            },
            {
                'id': 'field2',
                'type': 'string',
                'pattern': "dispatch_task('func2')"
            }
        ]
    }
    
    schema, _ = prepare_schema_unified(
        agent_config, 
        vendor='gemini',
        tools_path='/tmp/tools',
        context_data={}
    )
    
    props = schema['schema']
    assert props['field1']['description'] == 'resolved_func1'
    assert props['field2']['pattern'] == 'resolved_func2'
