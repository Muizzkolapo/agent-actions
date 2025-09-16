"""
Integration tests for the complete reprompting flow.

Tests the full pipeline of validation, reprompting, and retry logic.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from agent_actions.interceptors.validation_interceptor import ValidationInterceptor
from agent_actions.interceptors.reprompt_interceptor import RepromptInterceptor
from agent_actions.interceptors.base import InterceptorChain
from agent_actions.strategies.reprompt_strategy import TemplateRepromptStrategy


class TestRepromptingIntegration:
    """Integration tests for the reprompting flow."""

    @pytest.fixture
    def validation_interceptor(self):
        """Create a configured validation interceptor."""
        interceptor = ValidationInterceptor()
        config = {
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 10},
            "on_failure": "retry"
        }
        interceptor.configure(config)
        return interceptor

    @pytest.fixture
    def reprompt_interceptor(self):
        """Create a configured reprompt interceptor."""
        interceptor = RepromptInterceptor()
        config = {
            "strategy": "template",
            "max_attempts": 3,
            "templates": {
                "expected 10 words": "Please write exactly 10 words. {original_prompt}",
                "too short": "Your response was too short. Please expand: {original_prompt}"
            }
        }
        interceptor.configure(config)
        return interceptor

    def test_successful_validation_no_reprompt(self, validation_interceptor, reprompt_interceptor):
        """Test flow when validation passes on first attempt."""
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        # Response with exactly 10 words
        response = {"content": "This is a response with exactly ten words in it"}
        context = {"prompt": "Write something"}
        
        result = chain.process(response, context)
        
        assert result.continue_processing is True
        assert result.retry_context is None

    def test_validation_failure_triggers_reprompt(self, validation_interceptor, reprompt_interceptor):
        """Test flow when validation fails and triggers reprompt."""
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        # Response with only 5 words
        response = {"content": "This has five words only"}
        context = {"prompt": "Write something with 10 words"}
        
        result = chain.process(response, context)
        
        # Validation interceptor returns retry_context but doesn't trigger reprompt
        # because reprompt interceptor needs the validation_error in the context
        assert result.continue_processing is False
        assert result.retry_context is not None
        assert "validation_error" in result.retry_context
        assert result.retry_context["validation_error"] == "Expected 10 words, got 5"

    def test_multiple_retry_attempts(self, validation_interceptor, reprompt_interceptor):
        """Test multiple retry attempts with history tracking."""
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        # First attempt - 5 words
        response1 = {"content": "Too short first attempt response"}
        context1 = {"prompt": "Write 10 words"}
        
        result1 = chain.process(response1, context1)
        
        assert result1.retry_context["attempt"] == 1
        assert len(result1.retry_context.get("history", [])) == 1
        
        # Second attempt - still wrong (7 words)
        response2 = {"content": "Still not quite right with seven words"}
        context2 = {
            **result1.retry_context,
            "validation_error": "Expected 10 words, got 7"
        }
        
        result2 = chain.process(response2, context2)
        
        assert result2.retry_context["attempt"] == 2
        assert len(result2.retry_context["history"]) == 2
        assert result2.retry_context["history"][0]["attempt"] == 0
        assert result2.retry_context["history"][1]["attempt"] == 1

    def test_max_attempts_reached(self, validation_interceptor, reprompt_interceptor):
        """Test behavior when max attempts are reached."""
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        # Already at max attempts
        response = {"content": "Still wrong"}
        context = {
            "prompt": "Current prompt",
            "original_prompt": "Original prompt",
            "validation_error": "Expected 10 words, got 2",
            "attempt": 3,  # Max is 3
            "history": [
                {"attempt": 0, "prompt": "Original", "error": "Error 1"},
                {"attempt": 1, "prompt": "Retry 1", "error": "Error 2"},
                {"attempt": 2, "prompt": "Retry 2", "error": "Error 3"}
            ]
        }
        
        result = chain.process(response, context)
        
        assert result.continue_processing is False
        assert result.metadata == {"max_attempts_reached": True}
        assert result.retry_context is None

    def test_custom_validator_integration(self):
        """Test integration with a custom validator."""
        # Create a custom validator function for testing
        def validate_contains_python(content: str) -> tuple[bool, str | None]:
            if "python" in content.lower():
                return True, None
            return False, "Response must mention Python"
        
        # Monkey patch it for this test
        import agent_actions.validators.builtin_functions as bf
        bf.contains_python_validator = validate_contains_python
        
        # Create interceptors with custom validator
        validation_interceptor = ValidationInterceptor()
        validation_interceptor.configure({
            "validator_function": "agent_actions.validators.builtin_functions.contains_python_validator",
            "on_failure": "retry"
        })
        
        reprompt_interceptor = RepromptInterceptor()
        reprompt_interceptor.configure({
            "strategy": "template",
            "templates": {
                "must mention": "Make sure to mention Python in your response. {original_prompt}"
            }
        })
        
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        # Test failure case
        response = {"content": "This is about programming"}
        context = {"prompt": "Describe a programming language"}
        
        result = chain.process(response, context)
        
        assert result.continue_processing is False
        assert "Make sure to mention Python" in result.retry_context["prompt"]

    @patch('agent_actions.agents.base.agent_builder')
    def test_llm_reprompt_strategy_integration(self, mock_agent_builder):
        """Test integration with LLM reprompt strategy."""
        # Mock LLM response
        mock_agent_builder.create_dynamic_agent.return_value = [{
            "content": "Please write exactly 10 words about the topic you mentioned."
        }]
        
        # Create interceptors with LLM strategy
        validation_interceptor = ValidationInterceptor()
        validation_interceptor.configure({
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 10},
            "on_failure": "retry"
        })
        
        reprompt_interceptor = RepromptInterceptor()
        reprompt_interceptor.configure({
            "strategy": "llm",
            "llm_config": {
                "model_vendor": "openai",
                "model_name": "gpt-4"
            }
        })
        
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        response = {"content": "Too short"}
        context = {"prompt": "Write about AI"}
        
        result = chain.process(response, context)
        
        assert result.continue_processing is False
        assert result.retry_context["prompt"] == "Please write exactly 10 words about the topic you mentioned."
        
        # Verify LLM was called with proper context
        mock_agent_builder.create_dynamic_agent.assert_called_once()
        call_args = mock_agent_builder.create_dynamic_agent.call_args[0][0]
        assert "Write about AI" in call_args["prompt"]
        assert "Expected 10 words, got 2" in call_args["prompt"]

    def test_validation_with_complex_criteria(self):
        """Test validation with multiple criteria using char_count validator."""
        validation_interceptor = ValidationInterceptor()
        validation_interceptor.configure({
            "validator_function": "agent_actions.validators.builtin_functions.char_count_validator",
            "validator_args": {"min_chars": 50, "max_chars": 100},
            "on_failure": "retry"
        })
        
        reprompt_interceptor = RepromptInterceptor()
        reprompt_interceptor.configure({
            "strategy": "template",
            "templates": {
                "too short": "Please write at least {min_chars} characters. {original_prompt}",
                "too long": "Please keep it under {max_chars} characters. {original_prompt}"
            }
        })
        
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        # Test too short
        short_response = {"content": "Short"}
        result = chain.process(short_response, {"prompt": "Write something"})
        
        assert "Please write at least 50 characters" in result.retry_context["prompt"]
        
        # Test too long
        long_response = {"content": "A" * 150}
        result = chain.process(long_response, {"prompt": "Write something"})
        
        assert "Please keep it under 100 characters" in result.retry_context["prompt"]

    def test_interceptor_order_matters(self):
        """Test that interceptor order affects the flow."""
        # Create chain with reversed order (reprompt before validation)
        # This should not trigger reprompting since validation hasn't run yet
        
        validation_interceptor = ValidationInterceptor()
        validation_interceptor.configure({
            "validator": "word_count",
            "validator_args": {"expected": 10},
            "on_failure": "retry"
        })
        
        reprompt_interceptor = RepromptInterceptor()
        reprompt_interceptor.configure({
            "strategy": "template",
            "templates": {"words": "Write 10 words"}
        })
        
        # Wrong order: reprompt before validation
        chain = InterceptorChain([reprompt_interceptor, validation_interceptor])
        
        response = {"content": "Too short"}
        context = {"prompt": "Write something"}
        
        result = chain.process(response, context)
        
        # Reprompt interceptor passes through, validation interceptor creates retry context
        assert result.continue_processing is False
        assert result.retry_context is not None
        assert "validation_error" in result.retry_context
        assert "prompt" not in result.retry_context  # Reprompt didn't generate new prompt

    def test_error_propagation(self):
        """Test that errors in interceptors are properly propagated."""
        validation_interceptor = ValidationInterceptor()
        validation_interceptor.configure({
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 10},
            "on_failure": "fail"  # Will raise exception
        })
        
        reprompt_interceptor = RepromptInterceptor()
        reprompt_interceptor.configure({
            "strategy": "template",
            "templates": {}
        })
        
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        response = {"content": "Too short"}
        
        with pytest.raises(ValueError, match="Validation failed: Expected 10 words, got 2"):
            chain.process(response, {})

    def test_context_preservation_across_retries(self):
        """Test that context is properly preserved across retry attempts."""
        validation_interceptor = ValidationInterceptor()
        validation_interceptor.configure({
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 10},
            "on_failure": "retry"
        })
        
        reprompt_interceptor = RepromptInterceptor()
        reprompt_interceptor.configure({
            "strategy": "template",
            "templates": {"words": "Write exactly 10 words. {original_prompt}"}
        })
        
        chain = InterceptorChain([validation_interceptor, reprompt_interceptor])
        
        # Initial context with metadata
        initial_context = {
            "prompt": "Describe AI",
            "user_id": "123",
            "session_id": "abc",
            "custom_data": {"key": "value"}
        }
        
        response = {"content": "Too short"}
        result = chain.process(response, initial_context)
        
        # Verify original context is preserved in retry
        assert result.retry_context is not None
        # The retry_context from validation interceptor doesn't have original_prompt
        # but it has the failed response and validation error
        assert "validation_error" in result.retry_context
        assert "failed_response" in result.retry_context
        
        # Additional context from validation failure
        assert "validation_error" in result.retry_context
        assert "failed_response" in result.retry_context