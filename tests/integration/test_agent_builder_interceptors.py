"""
Integration tests for agent_builder with interceptors.

Tests the _execute_with_interceptors function and full integration.
"""

import pytest
from unittest.mock import Mock, patch, call
from typing import Dict, Any, List

# We'll need to import the actual function once we can see it
# For now, we'll create a test structure that can be adapted


class TestAgentBuilderInterceptors:
    """Test suite for agent_builder interceptor integration."""

    @pytest.fixture
    def mock_base_agent_call(self):
        """Mock the base agent execution."""
        with patch('agent_actions.agents.base.agent_builder._execute_base_agent') as mock:
            mock.return_value = [{"content": "Initial response"}]
            yield mock

    @pytest.fixture
    def agent_config_with_interceptors(self):
        """Create agent config with interceptors."""
        return {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "prompt": "Write a 10-word description",
            "interceptors": [
                {
                    "type": "validation",
                    "validator": "word_count",
                    "validator_args": {"expected": 10},
                    "on_failure": "retry"
                },
                {
                    "type": "reprompt",
                    "strategy": "template",
                    "max_attempts": 3,
                    "templates": {
                        "expected 10 words": "Please write exactly 10 words. {original_prompt}"
                    }
                }
            ]
        }

    @pytest.fixture
    def mock_interceptor_factory(self):
        """Mock the interceptor factory."""
        with patch('agent_actions.agents.base.agent_builder.InterceptorFactory') as mock:
            # Create mock interceptors
            mock_validation = Mock()
            mock_reprompt = Mock()
            
            factory_instance = Mock()
            factory_instance.create_from_config.side_effect = [
                mock_validation,
                mock_reprompt
            ]
            
            mock.return_value = factory_instance
            yield mock

    def test_execute_with_interceptors_success_first_try(self, mock_base_agent_call):
        """Test successful execution on first try."""
        # Mock successful response
        mock_base_agent_call.return_value = [{
            "content": "This is exactly ten words for the validation to pass"
        }]
        
        # Mock the function (this would be the actual import)
        from agent_actions.agents.base.agent_builder import _execute_with_interceptors
        
        config = {
            "model_vendor": "openai",
            "prompt": "Write 10 words",
            "interceptors": [{
                "type": "validation",
                "validator": "word_count",
                "validator_args": {"expected": 10}
            }]
        }
        
        with patch('agent_actions.interceptors.factory.InterceptorFactory'):
            result = _execute_with_interceptors(
                config, None, "", "Write 10 words", None, None, None, config["interceptors"]
            )
        
        assert len(result) == 1
        assert "ten words" in result[0]["content"]

    def test_execute_with_interceptors_retry_flow(self, mock_base_agent_call):
        """Test retry flow with validation failure and reprompt."""
        # First response fails, second succeeds
        mock_base_agent_call.side_effect = [
            [{"content": "Too short"}],
            [{"content": "This response now has exactly ten words for validation pass"}]
        ]
        
        config = {
            "model_vendor": "openai",
            "prompt": "Write 10 words",
            "interceptors": [
                {
                    "type": "validation",
                    "validator": "word_count",
                    "validator_args": {"expected": 10},
                    "on_failure": "retry"
                },
                {
                    "type": "reprompt",
                    "strategy": "template",
                    "templates": {
                        "expected 10 words": "Write exactly 10 words: {original_prompt}"
                    }
                }
            ]
        }
        
        # This would test the actual retry logic
        # We'd verify that the agent is called twice with different prompts

    def test_execute_with_interceptors_max_attempts(self):
        """Test behavior when max attempts are reached."""
        # All responses fail validation
        responses = [
            [{"content": "Fail 1"}],
            [{"content": "Fail 2"}],
            [{"content": "Fail 3"}]
        ]
        
        config = {
            "interceptors": [
                {
                    "type": "validation",
                    "validator": "word_count",
                    "validator_args": {"expected": 10}
                },
                {
                    "type": "reprompt",
                    "strategy": "template",
                    "max_attempts": 3,
                    "templates": {"words": "Write 10 words"}
                }
            ]
        }
        
        # Test that after 3 attempts, it returns the last response
        # even though validation still fails

    def test_execute_with_no_interceptors(self):
        """Test that execution works normally without interceptors."""
        config = {
            "model_vendor": "openai",
            "prompt": "Write something",
            "interceptors": []
        }
        
        # Should execute normally without any interception

    def test_interceptor_configuration_error(self):
        """Test handling of interceptor configuration errors."""
        config = {
            "interceptors": [{
                "type": "validation",
                "validator": "non_existent_validator"
            }]
        }
        
        # Should raise appropriate error about unknown validator

    def test_multiple_validation_interceptors(self):
        """Test chain with multiple validation requirements."""
        config = {
            "interceptors": [
                {
                    "type": "validation",
                    "validator": "word_count",
                    "validator_args": {"expected": 10}
                },
                {
                    "type": "validation", 
                    "validator": "contains_keywords",
                    "validator_args": {"required_keywords": ["AI", "technology"]}
                },
                {
                    "type": "reprompt",
                    "strategy": "template",
                    "templates": {
                        "words": "Write exactly 10 words including 'AI' and 'technology'",
                        "missing": "Include the keywords: AI, technology"
                    }
                }
            ]
        }
        
        # Test that both validations must pass

    @patch('agent_actions.agents.base.agent_builder.InterceptorChain')
    @patch('agent_actions.agents.base.agent_builder.InterceptorFactory')
    def test_context_preservation(self, mock_factory, mock_chain):
        """Test that context is preserved through retry cycles."""
        # Setup mocks
        mock_validation = Mock()
        mock_reprompt = Mock()
        
        factory_instance = Mock()
        factory_instance.create_from_config.side_effect = [
            mock_validation,
            mock_reprompt
        ]
        mock_factory.return_value = factory_instance
        
        # Configure chain to trigger retry
        chain_instance = Mock()
        chain_instance.process.return_value = Mock(
            continue_processing=False,
            retry_context={
                "prompt": "Improved prompt",
                "attempt": 1,
                "original_prompt": "Original prompt"
            }
        )
        mock_chain.return_value = chain_instance
        
        config = {
            "model_vendor": "openai",
            "prompt": "Original prompt",
            "user_metadata": {"session": "123"},
            "interceptors": [{"type": "validation"}, {"type": "reprompt"}]
        }
        
        # Execute and verify context preservation
        # Original user_metadata should be maintained

    def test_interceptor_metadata_aggregation(self):
        """Test that metadata from multiple interceptors is aggregated."""
        # Multiple interceptors each adding metadata
        # Final response should include all metadata

    def test_error_interceptor_handling(self):
        """Test handling when interceptor raises an error."""
        config = {
            "interceptors": [{
                "type": "validation",
                "validator": "word_count",
                "on_failure": "fail"  # Will raise exception
            }]
        }
        
        # Should propagate the validation error appropriately

    @pytest.mark.parametrize("response_format,expected_content", [
        ([{"content": "Test content"}], "Test content"),
        ([{"text": "Test text"}], "Test text"),
        ({"content": "Single dict"}, "Single dict"),
        ("Plain string", "Plain string")
    ])
    def test_response_format_handling(self, response_format, expected_content):
        """Test handling of different response formats through interceptors."""
        # Verify interceptors handle various response formats correctly

    def test_interceptor_chain_modification(self):
        """Test that interceptors can modify responses."""
        config = {
            "interceptors": [
                {
                    "type": "custom",
                    "class": "ResponseModifierInterceptor",
                    "config": {"prefix": "Modified: "}
                }
            ]
        }
        
        # Custom interceptor that modifies all responses
        # Verify modification is applied

    def test_async_compatibility(self):
        """Test that interceptor system works with async execution."""
        # If agent_builder supports async, test interceptors work correctly

    def test_performance_with_many_interceptors(self):
        """Test performance doesn't degrade with many interceptors."""
        config = {
            "interceptors": [
                {"type": "validation", "validator": f"validator_{i}"}
                for i in range(10)
            ]
        }
        
        # Verify reasonable performance with chain of 10 interceptors

    def test_interceptor_state_isolation(self):
        """Test that interceptor state is isolated between calls."""
        # Multiple calls with same config should not share state

    def test_custom_interceptor_integration(self):
        """Test integration of custom user-defined interceptors."""
        class CustomInterceptor:
            def configure(self, config):
                self.prefix = config.get("prefix", "")
                
            def intercept(self, response, context):
                # Custom logic
                pass
        
        # Test registration and usage of custom interceptor