"""
Integration tests for the complete reprompting flow.

Tests the realistic integration of validation and reprompting.
"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.interceptors.validation_interceptor import ValidationInterceptor
from agent_actions.interceptors.reprompt_interceptor import RepromptInterceptor
from agent_actions.interceptors.base import InterceptorChain
from agent_actions.interceptors.factory import InterceptorFactory


class TestRealisticRepromptingFlow:
    """Test realistic reprompting scenarios."""

    def test_validation_and_reprompt_integration(self):
        """Test realistic flow where validation fails and reprompt generates new prompt."""
        # Create chain using factory
        configs = [
            {
                "type": "validation",
                "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
                "validator_args": {"expected": 10},
                "on_failure": "retry"
            },
            {
                "type": "reprompt",
                "strategy": "template",
                "max_attempts": 3,
                "templates": {
                    "expected 10 words": "Please write exactly 10 words. Original request: {original_prompt}"
                }
            }
        ]
        
        chain = InterceptorFactory.build_chain(configs)
        
        # First attempt - validation fails
        response = {"content": "Too short"}
        context = {"prompt": "Write a description"}
        
        result = chain.process(response, context)
        
        # Validation interceptor should return retry context
        assert result.continue_processing is False
        assert result.retry_context is not None
        assert "validation_error" in result.retry_context
        assert result.retry_context["validation_error"] == "Expected 10 words, got 2"
        
        # In a real system, the retry_context would be used to retry the agent
        # For now, let's simulate the second attempt
        
        # Second attempt would use the retry_context to call reprompt interceptor
        reprompt_chain = InterceptorChain([chain.interceptors[1]])  # Just reprompt
        reprompt_result = reprompt_chain.process(response, result.retry_context)
        
        assert reprompt_result.continue_processing is False
        assert reprompt_result.retry_context is not None
        assert "prompt" in reprompt_result.retry_context
        assert "Please write exactly 10 words" in reprompt_result.retry_context["prompt"]

    def test_full_retry_loop_simulation(self):
        """Simulate a full retry loop with multiple attempts."""
        # Configuration
        validation_config = {
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 10},
            "on_failure": "retry"
        }
        
        reprompt_config = {
            "strategy": "template",
            "max_attempts": 3,
            "templates": {
                "expected 10 words": "Write exactly 10 words about {original_prompt}"
            }
        }
        
        # Create interceptors
        validator = ValidationInterceptor()
        validator.configure(validation_config)
        
        reprompt = RepromptInterceptor()
        reprompt.configure(reprompt_config)
        
        # Simulate retry loop
        attempts = []
        current_context = {"prompt": "AI technology"}
        
        for attempt in range(3):
            # Simulate agent response
            if attempt == 0:
                response = {"content": "AI is cool"}  # 3 words
            elif attempt == 1:
                response = {"content": "AI technology is very cool and useful"}  # 7 words
            else:
                response = {"content": "AI technology is transforming how we work and live today"}  # 10 words
            
            # Validate response
            val_result = validator.intercept(response, current_context)
            
            if val_result.continue_processing:
                # Success!
                attempts.append({"attempt": attempt, "success": True, "response": response})
                break
            
            # Failed validation - check if we can retry
            if attempt >= 2:  # Max attempts
                attempts.append({"attempt": attempt, "success": False, "max_attempts": True})
                break
            
            # Generate improved prompt
            reprompt_context = {
                **val_result.retry_context,
                "attempt": attempt,
                "original_prompt": current_context.get("original_prompt", current_context["prompt"])
            }
            reprompt_result = reprompt.intercept(response, reprompt_context)
            
            # Update context for next attempt
            current_context = reprompt_result.retry_context
            attempts.append({
                "attempt": attempt,
                "success": False,
                "new_prompt": current_context["prompt"]
            })
        
        # Verify the flow
        assert len(attempts) == 3
        assert attempts[0]["success"] is False
        assert "Write exactly 10 words about AI technology" in attempts[0]["new_prompt"]
        assert attempts[1]["success"] is False
        assert attempts[2]["success"] is True
        assert attempts[2]["response"]["content"] == "AI technology is transforming how we work and live today"

    def test_custom_validator_with_reprompt(self):
        """Test custom validator integration with reprompting."""
        # We'll create a custom validator function inline for testing
        def validate_positive_sentiment(content: str) -> tuple[bool, str | None]:
            negative_words = ["bad", "terrible", "awful", "hate", "worst"]
            content_lower = content.lower()
            for word in negative_words:
                if word in content_lower:
                    return False, f"Content contains negative word: '{word}'"
            return True, None
        
        # Monkey patch it into the builtin_functions for this test
        import agent_actions.validators.builtin_functions as bf
        bf.sentiment_positive_validator = validate_positive_sentiment
        
        # Build chain
        configs = [
            {
                "type": "validation",
                "validator_function": "agent_actions.validators.builtin_functions.sentiment_positive_validator",
                "on_failure": "retry"
            },
            {
                "type": "reprompt",
                "strategy": "template",
                "templates": {
                    "negative word": "Please rewrite with positive sentiment. Avoid negative words. {original_prompt}"
                }
            }
        ]
        
        chain = InterceptorFactory.build_chain(configs)
        
        # Test with negative content
        response = {"content": "This product is terrible and awful"}
        context = {"prompt": "Write a product review"}
        
        result = chain.process(response, context)
        
        assert result.continue_processing is False
        assert "Content contains negative word: 'terrible'" in result.retry_context["validation_error"]
        
        # Clean up
        if hasattr(bf, 'sentiment_positive_validator'):
            delattr(bf, 'sentiment_positive_validator')

    def test_multiple_validators_with_reprompt(self):
        """Test chain with multiple validators."""
        # First validator checks word count
        val1 = ValidationInterceptor()
        val1.configure({
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 10},
            "on_failure": "retry"
        })
        
        # Second validator checks keywords
        val2 = ValidationInterceptor()
        val2.configure({
            "validator_function": "agent_actions.validators.builtin_functions.keywords_validator",
            "validator_args": {"required_keywords": ["AI", "technology"]},
            "on_failure": "retry"
        })
        
        reprompt = RepromptInterceptor()
        reprompt.configure({
            "strategy": "template",
            "templates": {
                "expected 10 words": "Write exactly 10 words including 'AI' and 'technology'",
                "missing required keywords": "Include these keywords: AI, technology. {original_prompt}"
            }
        })
        
        chain = InterceptorChain([val1, val2, reprompt])
        
        # Test response that passes word count but fails keywords
        response = {"content": "This is exactly ten words for the validation to pass"}
        context = {"prompt": "Write about future tech"}
        
        result = chain.process(response, context)
        
        # Should fail on second validator
        assert result.continue_processing is False
        assert "Missing required keywords" in result.retry_context["validation_error"]

    @patch('agent_actions.models.agent_builder')
    def test_llm_reprompt_strategy_realistic(self, mock_agent_builder):
        """Test realistic LLM reprompt strategy."""
        # Mock LLM to return progressively better prompts
        mock_agent_builder.create_dynamic_agent.side_effect = [
            [{"content": "Please write exactly 10 words about artificial intelligence and its applications."}],
            [{"content": "Write a 10-word sentence describing how AI helps in healthcare specifically."}]
        ]
        
        configs = [
            {
                "type": "validation",
                "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
                "validator_args": {"expected": 10},
                "on_failure": "retry"
            },
            {
                "type": "reprompt",
                "strategy": "llm",
                "max_attempts": 3,
                "llm_config": {
                    "model_vendor": "openai",
                    "model_name": "gpt-4",
                    "temperature": 0.7
                }
            }
        ]
        
        chain = InterceptorFactory.build_chain(configs)
        
        # Process with chain (validation will fail)
        response = {"content": "AI helps"}
        val_result = chain.process(response, {"prompt": "Write about AI"})
        
        # Use reprompt interceptor with validation result
        reprompt = chain.interceptors[1]
        reprompt_result = reprompt.intercept(response, val_result.retry_context)
        
        assert reprompt_result.continue_processing is False
        assert reprompt_result.retry_context["prompt"] == "Please write exactly 10 words about artificial intelligence and its applications."
        
        # Verify LLM was called with proper context
        mock_agent_builder.create_dynamic_agent.assert_called_once()
        call_args = mock_agent_builder.create_dynamic_agent.call_args[0][0]
        assert "Expected 10 words, got 2" in call_args["prompt"]

    def test_edge_cases(self):
        """Test edge cases in the reprompting flow."""
        # Empty response
        validator = ValidationInterceptor()
        validator.configure({
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 5},
            "on_failure": "retry"
        })
        
        result = validator.intercept({"content": ""}, {})
        assert result.continue_processing is False
        assert result.retry_context["validation_error"] == "Expected 5 words, got 0"
        
        # None content
        result = validator.intercept({"content": None}, {})
        assert result.continue_processing is False
        
        # Missing content key
        result = validator.intercept({}, {})
        assert result.continue_processing is False