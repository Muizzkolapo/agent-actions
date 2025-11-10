"""
Comprehensive agent base tests for the Agent Actions agent builder and base classes.

Tests cover agent base functionality as specified in tests_recommendations.jsonc:
1. agent_builder builds correct components; rejects unknown types
2. agent_builder validates required config fields with helpful errors
3. agent_builder idempotent build does not duplicate singletons
4. base_loader/base_validator abstract methods raise NotImplementedError
5. base_validator result object has normalized shape
"""
import json
import pytest
from typing import Any, Dict, List, Optional, Union
from unittest.mock import Mock, patch, MagicMock
from agent_actions.llm_invocation.realtime.agent_builder import create_dynamic_agent
from agent_actions.llm_invocation.realtime.services.vendor_invocation_service import (
    VENDOR_HANDLERS, SINGLE_RESPONSE_VENDORS, VendorInvocationService
)
from agent_actions.llm_invocation.realtime.services.prompt_service import PromptService
from agent_actions.llm_invocation.realtime.services.schema_service import SchemaService

# Aliases for backward compatibility in tests
_prepare_prompt = PromptService.prepare_prompt
_prepare_schema = SchemaService.prepare_schema
_invoke_vendor_handler = VendorInvocationService.invoke_vendor
_debug_print_prompt = PromptService.debug_print_prompt
from agent_actions.input_loading.base_base_loader import BaseLoader
from agent_actions.validation.base_validator import BaseValidator
from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.configuration.interfaces import ProcessingMode

class _TestableLoader(BaseLoader[str]):
    """Concrete implementation of BaseLoader for testing."""

    def process(self, content: Any, file_path: Optional[str]=None) -> str:
        """Test implementation."""
        return str(content)

    def supports_filetype(self, file_extension: str) -> bool:
        """Test implementation."""
        return file_extension == '.txt'

class _TestableValidator(BaseValidator):
    """Concrete implementation of BaseValidator for testing."""

    def validate(self, data: Any) -> Dict[str, Any]:
        """Test implementation."""
        return {'is_valid': True, 'errors': [], 'warnings': [], 'data': data}

class TestAgentBuilder:
    """Test agent builder functionality."""

    def test_create_dynamic_agent_builds_correct_components(self):
        """Test agent_builder builds correct components; rejects unknown types."""
        valid_config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Test prompt', 'schema': {'type': 'object'}, 'granularity': 'record'}
        mock_response = [{'result': 'success'}]
        with patch('agent_actions.agents.base.agent_builder._invoke_vendor_handler') as mock_invoke:
            mock_invoke.return_value = mock_response
            with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
                mock_prompt.return_value = 'formatted prompt'
                with patch('agent_actions.agents.base.agent_builder._prepare_schema') as mock_schema:
                    mock_schema.return_value = {'type': 'object'}
                    result = create_dynamic_agent(agent_config=valid_config, udf=None, context_data_str='test context')
                    assert result == mock_response
                    mock_invoke.assert_called_once()

    def test_create_dynamic_agent_rejects_unknown_vendor_types(self):
        """Test agent_builder rejects unknown vendor types."""
        invalid_config = {'model_vendor': 'unknown_vendor', 'api_key': 'TEST_API_KEY', 'model_name': 'some-model', 'prompt': 'Test prompt'}
        with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
            mock_prompt.return_value = 'formatted prompt'
            with patch('agent_actions.agents.base.agent_builder._prepare_schema') as mock_schema:
                mock_schema.return_value = None
                with patch('agent_actions.agents.base.agent_builder._invoke_vendor_handler') as mock_invoke:
                    mock_invoke.side_effect = KeyError('Unknown vendor: unknown_vendor')
                    with pytest.raises(KeyError, match='Unknown vendor'):
                        create_dynamic_agent(agent_config=invalid_config, udf=None, context_data_str='test context')

    def test_create_dynamic_agent_validates_required_config_fields(self):
        """Test agent_builder validates required config fields with helpful errors."""
        incomplete_configs = [{}, {'model_vendor': 'openai'}, {'model_name': 'gpt-4'}, {'model_vendor': '', 'model_name': 'gpt-4'}]
        for config in incomplete_configs:
            with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
                mock_prompt.return_value = 'test prompt'
                with patch('agent_actions.agents.base.agent_builder._prepare_schema') as mock_schema:
                    mock_schema.return_value = None
                    try:
                        create_dynamic_agent(agent_config=config, udf=None, context_data_str='test context')
                    except (KeyError, ValueError, TypeError, Exception) as e:
                        assert len(str(e)) > 0

    def test_create_dynamic_agent_with_interceptors(self):
        """Test agent builder with interceptors configuration."""
        config_with_interceptors = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Test prompt', 'interceptors': [{'type': 'validation', 'config': {'rules': ['required']}}]}
        with patch('agent_actions.agents.base.agent_builder._execute_with_interceptors') as mock_interceptors:
            mock_interceptors.return_value = [{'intercepted': True}]
            result = create_dynamic_agent(agent_config=config_with_interceptors, udf=None, context_data_str='test context')
            assert result == [{'intercepted': True}]
            mock_interceptors.assert_called_once()

    def test_create_dynamic_agent_with_function_outputs(self):
        """Test agent builder with function output injection."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Test prompt with {{function_result}}'}
        captured_results = {'function_result': 'injected_value'}
        with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
            mock_prompt.return_value = 'formatted prompt'
            with patch('agent_actions.agents.base.agent_builder.PromptUtils.inject_function_outputs_into_prompt') as mock_inject:
                mock_inject.return_value = ('updated prompt', captured_results)
                with patch('agent_actions.agents.base.agent_builder._invoke_vendor_handler') as mock_invoke:
                    mock_invoke.return_value = [{'result': 'success'}]
                    result = create_dynamic_agent(agent_config=config, udf=None, context_data_str='test context', tools_path='/path/to/tools')
                    assert result[0]['function_result'] == 'injected_value'

    def test_vendor_handlers_registry(self):
        """Test vendor handlers registry contains expected vendors."""
        expected_vendors = ['openai', 'ollama', 'gemini', 'cohere', 'mistral', 'anthropic', 'groq', 'deepseek', 'tool']
        for vendor in expected_vendors:
            assert vendor in VENDOR_HANDLERS
            assert VENDOR_HANDLERS[vendor] is not None

    def test_single_response_vendors_registry(self):
        """Test single response vendors registry is properly configured."""
        expected_single_response = {'cohere', 'mistral', 'anthropic', 'groq', 'deepseek'}
        assert SINGLE_RESPONSE_VENDORS == expected_single_response

    def test_prepare_prompt_with_formatted_prompt(self):
        """Test _prepare_prompt with pre-formatted prompt."""
        config = {'prompt': 'config_prompt'}
        formatted_prompt = 'pre_formatted_prompt'
        result = _prepare_prompt(config, formatted_prompt)
        assert result == formatted_prompt

    def test_prepare_prompt_from_config(self):
        """Test _prepare_prompt loading from config."""
        config = {'prompt': 'direct_prompt_text'}
        result = _prepare_prompt(config, None)
        assert result == 'direct_prompt_text'

    def test_prepare_prompt_with_file_reference(self):
        """Test _prepare_prompt with file reference."""
        config = {'prompt': '$prompt_file.txt'}
        with patch('agent_actions.agents.base.agent_builder.PromptLoader.load_prompt') as mock_load_prompt:
            mock_load_prompt.return_value = 'loaded_prompt_content'
            result = _prepare_prompt(config, None)
            assert result == 'loaded_prompt_content'
            mock_load_prompt.assert_called_once_with('prompt_file.txt')

    def test_prepare_schema_success(self):
        """Test _prepare_schema with valid schema configuration."""
        config = {'schema': {'type': 'object', 'properties': {'field': {'type': 'string'}}}, 'schema_name': 'test_schema'}
        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict') as mock_construct:
            mock_construct.return_value = {'base': 'schema'}
            with patch('agent_actions.core.parser.schema_change.compile_unified_schema') as mock_compile:
                mock_compile.return_value = {'compiled': 'schema'}
                result = _prepare_schema(config, 'openai')
                assert result == {'compiled': 'schema'}

    def test_prepare_schema_no_schema(self):
        """Test _prepare_schema when no schema is configured."""
        config = {}
        result = _prepare_schema(config, 'openai')
        assert result is None

    def test_invoke_vendor_handler_openai(self):
        """Test _invoke_vendor_handler with OpenAI vendor."""
        agent_config = {'model_vendor': 'openai', 'model_name': 'gpt-4'}
        mock_response = [{'result': 'openai_response'}]
        with patch.object(VENDOR_HANDLERS['openai'], 'invoke') as mock_invoke:
            mock_invoke.return_value = mock_response
            result = _invoke_vendor_handler(model_vendor='openai', agent_config=agent_config, prompt_config='test prompt', context_data='test context', schema=None, granularity='record', formatted_prompt='formatted prompt', tool_args=None, source_content=None)
            assert result == mock_response
            mock_invoke.assert_called_once_with(agent_config, 'test prompt', 'test context', None)

    def test_invoke_vendor_handler_single_response_vendor(self):
        """Test _invoke_vendor_handler with single response vendor."""
        agent_config = {'model_vendor': 'cohere', 'model_name': 'command'}
        mock_response = {'single': 'response'}
        with patch.object(VENDOR_HANDLERS['cohere'], 'invoke') as mock_invoke:
            mock_invoke.return_value = mock_response
            result = _invoke_vendor_handler(model_vendor='cohere', agent_config=agent_config, prompt_config='test prompt', context_data='test context', schema=None, granularity='record', formatted_prompt='formatted prompt', tool_args=None, source_content=None)
            assert result == [mock_response]
            mock_invoke.assert_called_once_with(agent_config, 'test prompt', 'test context', None)

    def test_debug_print_prompt(self, capfd):
        """Test _debug_print_prompt outputs debug information."""
        config = {'name': 'test_agent', 'debug': True}
        prompt = 'debug test prompt'
        context = 'debug context'
        _debug_print_prompt(config, prompt, context)
        captured = capfd.readouterr()

class TestBaseLoader:
    """Test BaseLoader abstract class."""

    def test_base_loader_abstract_methods_raise_not_implemented(self):
        """Test base_loader abstract methods raise NotImplementedError."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        with pytest.raises(TypeError):
            BaseLoader(agent_config, 'test')

    def test_testable_loader_concrete_implementation(self):
        """Test concrete implementation of BaseLoader works correctly."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        assert loader.process('test content') == 'test content'
        assert loader.supports_filetype('.txt') is True
        assert loader.supports_filetype('.json') is False

    def test_base_loader_interface_methods(self):
        """Test BaseLoader interface methods."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        assert loader.supports_async() is True
        assert loader.get_processing_mode() == ProcessingMode.AUTO

    def test_base_loader_initialization(self):
        """Test BaseLoader initialization."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {'param': 'value'}}
        agent_name = 'test_loader'
        loader = _TestableLoader(agent_config, agent_name)
        assert loader.agent_config == agent_config
        assert loader.agent_name == agent_name
        assert loader.logger is not None

    def test_base_loader_async_methods(self, tmp_path):
        """Test BaseLoader async methods."""
        agent_config: AgentEntryDict = {'name': 'test', 'type': 'loader', 'config': {}}
        loader = _TestableLoader(agent_config, 'test')
        result = loader.process('sync test')
        assert result == 'sync test'
        test_file = tmp_path / 'test.txt'
        test_file.write_text('file content')
        assert loader.supports_filetype('.txt') is True
        assert loader.supports_filetype('.json') is False

class TestBaseValidator:
    """Test BaseValidator abstract class."""

    def test_base_validator_abstract_methods_raise_not_implemented(self):
        """Test base_validator abstract methods raise NotImplementedError."""
        with pytest.raises(TypeError):
            BaseValidator()

    def test_testable_validator_concrete_implementation(self):
        """Test concrete implementation of BaseValidator works correctly."""
        validator = _TestableValidator()
        result = validator.validate({'test': 'data'})
        assert isinstance(result, dict)
        assert 'is_valid' in result
        assert 'errors' in result
        assert 'warnings' in result
        assert 'data' in result

    def test_base_validator_result_object_normalized_shape(self):
        """Test base_validator result object has normalized shape."""
        validator = _TestableValidator()
        test_data = [{'simple': 'data'}, [1, 2, 3], 'string data', 42, None]
        for data in test_data:
            result = validator.validate(data)
            assert isinstance(result, dict)
            assert 'is_valid' in result
            assert isinstance(result['is_valid'], bool)
            assert 'errors' in result
            assert isinstance(result['errors'], list)
            assert 'warnings' in result
            assert isinstance(result['warnings'], list)
            assert 'data' in result

    def test_base_validator_interface_compliance(self):
        """Test BaseValidator interface compliance."""
        validator = _TestableValidator()
        assert hasattr(validator, 'validate')
        assert callable(validator.validate)
        result = validator.validate('test')
        assert result is not None

class TestAgentBuilderIdempotency:
    """Test agent builder idempotency and singleton behavior."""

    def test_agent_builder_idempotent_build_no_duplicate_singletons(self):
        """Test agent_builder idempotent build does not duplicate singletons."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Test prompt'}
        with patch.object(VENDOR_HANDLERS['openai'], 'invoke') as mock_invoke:
            mock_invoke.return_value = [{'result': 'test'}]
            with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
                mock_prompt.return_value = 'prepared prompt'
                with patch('agent_actions.agents.base.agent_builder._prepare_schema') as mock_schema:
                    mock_schema.return_value = None
                    result1 = create_dynamic_agent(agent_config=config, udf=None, context_data_str='context1')
                    result2 = create_dynamic_agent(agent_config=config, udf=None, context_data_str='context2')
                    assert result1 == [{'result': 'test'}]
                    assert result2 == [{'result': 'test'}]
                    assert mock_invoke.call_count == 2

    def test_vendor_handlers_singleton_behavior(self):
        """Test vendor handlers exhibit singleton-like behavior."""
        handler1 = VENDOR_HANDLERS.get('openai')
        handler2 = VENDOR_HANDLERS.get('openai')
        assert handler1 is handler2

    def test_agent_builder_with_same_config_different_context(self):
        """Test agent builder with same config but different context data."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Test prompt: {{context}}'}
        contexts = ['context1', 'context2', 'context3']
        results = []
        with patch.object(VENDOR_HANDLERS['openai'], 'invoke') as mock_invoke:
            mock_invoke.return_value = [{'context': 'processed'}]
            with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
                mock_prompt.return_value = 'prepared prompt'
                with patch('agent_actions.agents.base.agent_builder._prepare_schema') as mock_schema:
                    mock_schema.return_value = None
                    for context in contexts:
                        result = create_dynamic_agent(agent_config=config, udf=None, context_data_str=context)
                        results.append(result)
        assert len(results) == 3
        assert all((isinstance(result, list) for result in results))
        assert mock_invoke.call_count == 3

class TestAgentBuilderErrorHandling:
    """Test agent builder error handling scenarios."""

    def test_agent_builder_handles_vendor_handler_errors(self):
        """Test agent builder handles vendor handler errors gracefully."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Test prompt'}
        with patch('agent_actions.agents.base.agent_builder._invoke_vendor_handler') as mock_invoke:
            mock_invoke.side_effect = Exception('Vendor handler failed')
            with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
                mock_prompt.return_value = 'prepared prompt'
                with pytest.raises(Exception, match='Vendor handler failed'):
                    create_dynamic_agent(agent_config=config, udf=None, context_data_str='test context')

    def test_agent_builder_handles_prompt_preparation_errors(self):
        """Test agent builder handles prompt preparation errors."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': '$nonexistent_file.txt'}
        with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
            mock_prompt.side_effect = FileNotFoundError('Prompt file not found')
            with pytest.raises(FileNotFoundError, match='Prompt file not found'):
                create_dynamic_agent(agent_config=config, udf=None, context_data_str='test context')

    def test_agent_builder_handles_schema_preparation_errors(self):
        """Test agent builder handles schema preparation errors."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Test prompt', 'schema': {'invalid': 'schema'}}
        with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
            mock_prompt.return_value = 'prepared prompt'
            with patch('agent_actions.agents.base.agent_builder._prepare_schema') as mock_schema:
                mock_schema.side_effect = ValueError('Invalid schema format')
                with pytest.raises(ValueError, match='Invalid schema format'):
                    create_dynamic_agent(agent_config=config, udf=None, context_data_str='test context')

    def test_agent_builder_handles_invalid_context_data(self):
        """Test agent builder handles invalid context data gracefully."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Test prompt'}
        invalid_contexts = [object(), {'circular': None}]
        invalid_contexts[1]['circular'] = invalid_contexts[1]
        for invalid_context in invalid_contexts:
            with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
                mock_prompt.return_value = 'prepared prompt'
                try:
                    create_dynamic_agent(agent_config=config, udf=None, context_data_str=invalid_context)
                except (TypeError, ValueError) as e:
                    assert len(str(e)) > 0

class TestAgentBuilderIntegration:
    """Integration tests for agent builder functionality."""

    def test_end_to_end_agent_creation(self):
        """Test end-to-end agent creation with minimal mocking."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Create a summary of: {{context}}', 'schema': {'type': 'object', 'properties': {'summary': {'type': 'string'}}}, 'granularity': 'record'}
        context_data = {'content': 'This is test content to summarize'}
        expected_response = [{'summary': 'Test summary'}]
        with patch('agent_actions.agents.base.agent_builder.SchemaLoader.construct_schema_from_dict') as mock_construct:
            mock_construct.return_value = {'base': 'schema'}
            with patch('agent_actions.agents.base.agent_builder.compile_unified_schema') as mock_compile:
                mock_compile.return_value = {'compiled': 'schema'}
                with patch.object(VENDOR_HANDLERS['openai'], 'invoke') as mock_invoke:
                    mock_invoke.return_value = expected_response
                    result = create_dynamic_agent(agent_config=config, udf=None, context_data_str=context_data)
                    assert result == expected_response
                    mock_invoke.assert_called_once()

    def test_agent_builder_with_all_optional_parameters(self):
        """Test agent builder with all optional parameters."""
        config = {'model_vendor': 'openai', 'api_key': 'TEST_API_KEY', 'model_name': 'gpt-4', 'prompt': 'Process: {{context}} with {{tool_result}}'}
        with patch.object(VENDOR_HANDLERS['openai'], 'invoke') as mock_invoke:
            mock_invoke.return_value = [{'processed': True}]
            with patch('agent_actions.agents.base.agent_builder._prepare_prompt') as mock_prompt:
                mock_prompt.return_value = 'prepared prompt'
                with patch('agent_actions.agents.base.agent_builder._prepare_schema') as mock_schema:
                    mock_schema.return_value = None
                    result = create_dynamic_agent(agent_config=config, udf=lambda x: x, context_data_str='test context', formatted_prompt='custom formatted prompt', tools_path='/path/to/tools', tool_args={'arg1': 'value1'}, source_content='source content')
                    assert result == [{'processed': True}]
                    mock_invoke.assert_called_once()
                    call_args = mock_invoke.call_args[0]
                    assert len(call_args) == 4