"""
Unit tests for RepromptInterceptor.

Tests reprompt generation, max attempts, and strategy integration.
"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.agents.interceptors.reprompt_interceptor import RepromptInterceptor
from agent_actions.agents.interceptors.base import InterceptorResult
from agent_actions.strategies.reprompt_strategy import (
    RepromptContext,
    LLMRepromptStrategy,
    TemplateRepromptStrategy
)


class TestRepromptInterceptor:
    """Test suite for RepromptInterceptor."""

    @pytest.fixture
    def interceptor(self):
        """Create a RepromptInterceptor instance."""
        return RepromptInterceptor()

    @pytest.fixture
    def mock_strategy(self):
        """Create a mock reprompt strategy."""
        strategy = Mock()
        strategy.generate_improved_prompt.return_value = "Improved prompt"
        return strategy

    def test_init(self, interceptor):
        """Test interceptor initialization."""
        assert interceptor.strategy is None
        assert interceptor.max_attempts == 3

    def test_configure_llm_strategy(self, interceptor):
        """Test configuration with LLM strategy."""
        config = {
            "strategy": "llm",
            "max_attempts": 5,
            "llm_config": {"model_name": "gpt-4"}
        }
        
        with patch('agent_actions.interceptors.reprompt_interceptor.LLMRepromptStrategy') as MockLLM:
            interceptor.configure(config)
            
            assert interceptor.max_attempts == 5
            MockLLM.assert_called_once_with({"model_name": "gpt-4"})
            assert interceptor.strategy == MockLLM.return_value

    def test_configure_template_strategy(self, interceptor):
        """Test configuration with template strategy."""
        config = {
            "strategy": "template",
            "templates": {"too short": "Please provide more detail: {original_prompt}"}
        }
        
        with patch('agent_actions.interceptors.reprompt_interceptor.TemplateRepromptStrategy') as MockTemplate:
            interceptor.configure(config)
            
            MockTemplate.assert_called_once_with({"too short": "Please provide more detail: {original_prompt}"})
            assert interceptor.strategy == MockTemplate.return_value

    def test_configure_invalid_strategy(self, interceptor):
        """Test configuration with invalid strategy."""
        config = {"strategy": "invalid"}
        
        with pytest.raises(ValueError, match="Unknown reprompt strategy: invalid"):
            interceptor.configure(config)

    def test_intercept_no_validation_error(self, interceptor, mock_strategy):
        """Test intercept when there's no validation error."""
        interceptor.strategy = mock_strategy
        
        result = interceptor.intercept("response", {})
        
        assert result.continue_processing is True
        mock_strategy.generate_improved_prompt.assert_not_called()

    def test_intercept_max_attempts_reached(self, interceptor, mock_strategy):
        """Test intercept when max attempts are reached."""
        interceptor.strategy = mock_strategy
        interceptor.max_attempts = 3
        
        context = {
            "validation_error": "Too short",
            "attempt": 3
        }
        
        result = interceptor.intercept("response", context)
        
        assert result.continue_processing is False
        assert result.metadata == {"max_attempts_reached": True}
        mock_strategy.generate_improved_prompt.assert_not_called()

    def test_intercept_generate_reprompt(self, interceptor, mock_strategy):
        """Test successful reprompt generation."""
        interceptor.strategy = mock_strategy
        
        context = {
            "validation_error": "Too short",
            "prompt": "Original prompt",
            "validator_args": {"min_length": 100},
            "failed_response": "Short response",
            "agent_config": {"model": "gpt-4"},
            "attempt": 1
        }
        
        result = interceptor.intercept("response", context)
        
        assert result.continue_processing is False
        assert result.retry_context == {
            "prompt": "Improved prompt",
            "original_prompt": "Original prompt",
            "attempt": 2,
            "history": [{
                "attempt": 1,
                "prompt": "Original prompt",
                "error": "Too short"
            }]
        }
        
        # Verify RepromptContext was created correctly
        mock_strategy.generate_improved_prompt.assert_called_once()
        call_args = mock_strategy.generate_improved_prompt.call_args[0][0]
        assert isinstance(call_args, RepromptContext)
        assert call_args.original_prompt == "Original prompt"
        assert call_args.validation_error == "Too short"
        assert call_args.attempt_number == 2

    def test_intercept_preserves_history(self, interceptor, mock_strategy):
        """Test that attempt history is preserved."""
        interceptor.strategy = mock_strategy
        
        context = {
            "validation_error": "Still too short",
            "prompt": "Second attempt prompt",
            "original_prompt": "Original prompt",
            "attempt": 1,
            "history": [{
                "attempt": 0,
                "prompt": "Original prompt",
                "error": "Too short"
            }]
        }
        
        result = interceptor.intercept("response", context)
        
        assert len(result.retry_context["history"]) == 2
        assert result.retry_context["history"][0] == {
            "attempt": 0,
            "prompt": "Original prompt",
            "error": "Too short"
        }
        assert result.retry_context["history"][1] == {
            "attempt": 1,
            "prompt": "Second attempt prompt",
            "error": "Still too short"
        }

    def test_intercept_no_strategy_configured(self, interceptor):
        """Test intercept when strategy is not configured."""
        context = {"validation_error": "Error"}
        
        with pytest.raises(ValueError, match="Reprompt strategy not configured"):
            interceptor.intercept("response", context)

    def test_intercept_uses_original_prompt_fallback(self, interceptor, mock_strategy):
        """Test that original_prompt falls back to prompt if not provided."""
        interceptor.strategy = mock_strategy
        
        context = {
            "validation_error": "Error",
            "prompt": "Current prompt",
            # No "original_prompt" key
        }
        
        result = interceptor.intercept("response", context)
        
        call_args = mock_strategy.generate_improved_prompt.call_args[0][0]
        assert call_args.original_prompt == "Current prompt"

    def test_full_reprompt_flow(self, interceptor):
        """Test full reprompt flow with actual strategy."""
        templates = {
            "too short": "Please provide a more detailed response. {original_prompt}"
        }
        
        config = {
            "strategy": "template",
            "max_attempts": 2,
            "templates": templates
        }
        
        interceptor.configure(config)
        
        context = {
            "validation_error": "Response too short",
            "prompt": "Write a story",
            "attempt": 0
        }
        
        result = interceptor.intercept("response", context)
        
        assert result.continue_processing is False
        assert "Please provide a more detailed response. Write a story" in result.retry_context["prompt"]
        assert result.retry_context["attempt"] == 1

    @pytest.mark.parametrize("attempt,max_attempts,should_retry", [
        (0, 3, True),
        (1, 3, True),
        (2, 3, True),
        (3, 3, False),
        (4, 3, False),
        (0, 1, True),
        (1, 1, False),
    ])
    def test_max_attempts_logic(self, interceptor, mock_strategy, attempt, max_attempts, should_retry):
        """Test max attempts logic with various configurations."""
        interceptor.strategy = mock_strategy
        interceptor.max_attempts = max_attempts
        
        context = {
            "validation_error": "Error",
            "attempt": attempt
        }
        
        result = interceptor.intercept("response", context)
        
        if should_retry:
            assert result.retry_context is not None
            assert result.retry_context["attempt"] == attempt + 1
        else:
            assert result.metadata == {"max_attempts_reached": True}
            assert result.retry_context is None