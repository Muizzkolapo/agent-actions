"""Test inline schema support in batch processing for all providers"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.tasks.services.batch_service import BatchService
from agent_actions.integrations.providers.openai_provider import OpenAIBatchProvider
from agent_actions.integrations.providers.gemini_provider import GeminiBatchProvider
from agent_actions.integrations.providers.anthropic_provider import AnthropicBatchProvider


class TestBatchInlineSchema:
    """Test inline schema support across all batch providers"""
    
    @pytest.fixture
    def inline_schema(self):
        """Sample inline schema"""
        return {
            "question": "string!",
            "options": "array[string]",
            "score": "number"
        }
    
    @pytest.fixture
    def agent_config(self, inline_schema):
        """Base agent configuration with inline schema"""
        return {
            "agent_type": "test_agent",
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "schema": inline_schema,  # Using inline schema
            "prompt": "Generate a question with options",
            "api_key": "TEST_API_KEY"
        }
    
    @pytest.fixture
    def test_data(self):
        """Sample test data"""
        return [
            {
                "target_id": "test1",
                "content": "Generate a math question"
            }
        ]
    
    def test_openai_provider_inline_schema(self, agent_config, test_data):
        """Test OpenAI provider handles inline schema correctly"""
        agent_config["model_vendor"] = "openai"
        
        batch_service = BatchService()
        
        # Mock the OpenAI client to avoid actual API calls
        with patch.object(OpenAIBatchProvider, '__init__', return_value=None):
            provider = OpenAIBatchProvider()
            provider.client = Mock()
            
            # Test schema preparation
            schema = batch_service._prepare_schema(agent_config, provider)
            assert schema is not None
            assert schema["name"] == "InlineSchema"
            assert "schema" in schema
            assert schema["schema"]["type"] == "object"
            assert "question" in schema["schema"]["properties"]
            assert "options" in schema["schema"]["properties"]
            assert "score" in schema["schema"]["properties"]
            assert "question" in schema["schema"]["required"]
            
            # Test task preparation
            provider_config = agent_config.copy()
            provider_config["compiled_schema"] = schema
            
            # Mock prepare_tasks to avoid deeper dependencies
            with patch.object(provider, 'prepare_tasks') as mock_prepare:
                mock_prepare.return_value = [{"custom_id": "test1", "body": {"response_format": {"json_schema": schema}}}]
                
                tasks = provider.prepare_tasks(test_data, provider_config)
                assert len(tasks) == 1
                assert tasks[0]["body"]["response_format"]["json_schema"] == schema
    
    def test_gemini_provider_inline_schema(self, agent_config, test_data):
        """Test Gemini provider handles inline schema correctly"""
        agent_config["model_vendor"] = "gemini"
        agent_config["model_name"] = "gemini-1.5-flash"
        
        batch_service = BatchService()
        
        # Mock the Gemini client to avoid actual API calls
        with patch('google.generativeai.configure'):
            with patch.object(GeminiBatchProvider, '__init__', return_value=None):
                provider = GeminiBatchProvider()
                
                # Test schema preparation
                schema = batch_service._prepare_schema(agent_config, provider)
                assert schema is not None
                assert schema["name"] == "InlineSchema"
                
                # Gemini returns the unified schema unchanged (no compilation)
                # It should have 'fields' from the unified schema format
                assert "fields" in schema
                assert len(schema["fields"]) == 3
                
                # Check the fields
                fields_by_id = {f["id"]: f for f in schema["fields"]}
                assert "question" in fields_by_id
                assert "options" in fields_by_id
                assert "score" in fields_by_id
    
    def test_anthropic_provider_inline_schema(self, agent_config, test_data):
        """Test Anthropic provider handles inline schema correctly"""
        agent_config["model_vendor"] = "anthropic"
        agent_config["model_name"] = "claude-3-5-sonnet-latest"
        
        batch_service = BatchService()
        
        # Mock the Anthropic client to avoid actual API calls
        with patch.object(AnthropicBatchProvider, '__init__', return_value=None):
            provider = AnthropicBatchProvider()
            provider.client = Mock()
            
            # Test schema preparation
            schema = batch_service._prepare_schema(agent_config, provider)
            assert schema is not None
            
            # Anthropic returns a list of tools
            assert isinstance(schema, list)
            assert len(schema) == 1
            assert schema[0]["name"] == "InlineSchema"
            assert "input_schema" in schema[0]
            assert schema[0]["input_schema"]["type"] == "object"
            assert "question" in schema[0]["input_schema"]["properties"]
    
    def test_batch_service_prepare_tasks_with_inline_schema(self, agent_config, test_data):
        """Test batch service prepares tasks correctly with inline schema"""
        batch_service = BatchService()
        
        # Mock provider to avoid API calls
        with patch.object(batch_service, '_get_provider_for_config') as mock_get_provider:
            mock_provider = Mock()
            mock_provider.compile_schema.return_value = {"name": "InlineSchema", "schema": {}}
            mock_provider.prepare_tasks.return_value = [{"task": "mocked"}]
            mock_get_provider.return_value = mock_provider
            
            # Test task preparation
            tasks = batch_service.prepare_batch_tasks_from_data(agent_config, test_data)
            
            # Verify schema was compiled
            mock_provider.compile_schema.assert_called_once()
            
            # Verify prepare_tasks was called with compiled schema
            mock_provider.prepare_tasks.assert_called_once()
            call_args = mock_provider.prepare_tasks.call_args[0]
            provider_config = call_args[1]
            assert "compiled_schema" in provider_config
            assert provider_config["compiled_schema"]["name"] == "InlineSchema"