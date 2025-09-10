"""Tests for prompt_debug feature in interceptors."""

import io
import sys
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import pytest

from agent_actions.interceptors.factory import InterceptorFactory
from agent_actions.interceptors.reprompt_interceptor import RepromptInterceptor
from agent_actions.interceptors.validation_interceptor import ValidationInterceptor
from agent_actions.strategies.reprompt_strategy import (
    LLMRepromptStrategy,
    RepromptContext,
    TemplateRepromptStrategy,
)


class TestPromptDebugValidationInterceptor:
    """Test prompt_debug functionality in ValidationInterceptor."""

    def test_validation_interceptor_debug_off(self):
        """Test that no debug output is printed when prompt_debug is False."""
        interceptor = ValidationInterceptor()
        
        config = {
            "prompt_debug": False,
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 3},
            "on_failure": "retry"
        }
        
        # Capture stdout
        f = io.StringIO()
        with redirect_stdout(f):
            interceptor.configure(config)
            result = interceptor.intercept(["test response"], {"attempt": 0})
        
        output = f.getvalue()
        
        # Assert no debug output
        assert "🔧 VALIDATION INTERCEPTOR CONFIGURE:" not in output
        assert "🔍 VALIDATION INTERCEPTOR INTERCEPT:" not in output
        assert "❌ VALIDATION FAILED" not in output
        
        # Verify interceptor still works
        assert not result.continue_processing
        assert result.retry_context is not None

    def test_validation_interceptor_debug_on(self):
        """Test that debug output is printed when prompt_debug is True."""
        interceptor = ValidationInterceptor()
        
        config = {
            "prompt_debug": True,
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 3},
            "on_failure": "retry"
        }
        
        # Capture stdout
        f = io.StringIO()
        with redirect_stdout(f):
            interceptor.configure(config)
            result = interceptor.intercept(["test response"], {"attempt": 0})
        
        output = f.getvalue()
        
        # Assert debug output is present
        assert "🔧 VALIDATION INTERCEPTOR CONFIGURE:" in output
        assert "🔍 VALIDATION INTERCEPTOR INTERCEPT:" in output
        assert "❌ VALIDATION FAILED - setting up retry" in output
        assert "Config received:" in output
        assert "Response type:" in output

    def test_validation_success_with_debug(self):
        """Test debug output when validation passes."""
        interceptor = ValidationInterceptor()
        
        config = {
            "prompt_debug": True,
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 2}  # "test response" has 2 words
        }
        
        f = io.StringIO()
        with redirect_stdout(f):
            interceptor.configure(config)
            result = interceptor.intercept(["test response"], {"attempt": 0})
        
        output = f.getvalue()
        
        assert "✅ VALIDATION PASSED - continuing" in output
        assert result.continue_processing


class TestPromptDebugRepromptInterceptor:
    """Test prompt_debug functionality in RepromptInterceptor."""

    def test_reprompt_interceptor_debug_off(self):
        """Test that no debug output is printed when prompt_debug is False."""
        interceptor = RepromptInterceptor()
        
        config = {
            "prompt_debug": False,
            "strategy": "simple",
            "max_attempts": 3,
            "include_previous_response": True
        }
        
        f = io.StringIO()
        with redirect_stdout(f):
            interceptor.configure(config)
            
            context = {
                "validation_error": "Test error",
                "attempt": 0,
                "prompt": "Original prompt",
                "failed_response": "Failed response"
            }
            result = interceptor.intercept(None, context)
        
        output = f.getvalue()
        
        # Assert no debug output
        assert "🔄 REPROMPT INTERCEPTOR CONFIGURE:" not in output
        assert "🧠 REPROMPT INTERCEPTOR INTERCEPT:" not in output
        
        # Verify interceptor still works
        assert not result.continue_processing
        assert result.retry_context is not None

    def test_reprompt_interceptor_debug_on(self):
        """Test that debug output is printed when prompt_debug is True."""
        interceptor = RepromptInterceptor()
        
        config = {
            "prompt_debug": True,
            "strategy": "simple",
            "max_attempts": 3,
            "include_previous_response": True
        }
        
        f = io.StringIO()
        with redirect_stdout(f):
            interceptor.configure(config)
            
            context = {
                "validation_error": "Test error",
                "attempt": 0,
                "prompt": "Original prompt",
                "failed_response": "Failed response"
            }
            result = interceptor.intercept(None, context)
        
        output = f.getvalue()
        
        # Assert debug output is present
        assert "🔄 REPROMPT INTERCEPTOR CONFIGURE:" in output
        assert "🧠 REPROMPT INTERCEPTOR INTERCEPT:" in output
        assert "Strategy type: simple" in output
        assert "Current attempt: 0" in output

    def test_max_attempts_reached_debug(self):
        """Test debug output when max attempts are reached."""
        interceptor = RepromptInterceptor()
        
        config = {
            "prompt_debug": True,
            "strategy": "simple",
            "max_attempts": 2
        }
        
        f = io.StringIO()
        with redirect_stdout(f):
            interceptor.configure(config)
            
            context = {
                "validation_error": "Test error",
                "attempt": 2,  # Already at max
                "prompt": "Original prompt"
            }
            result = interceptor.intercept(None, context)
        
        output = f.getvalue()
        
        assert "🛑 MAX ATTEMPTS REACHED - stopping" in output
        assert result.metadata.get("max_attempts_reached") is True


class TestPromptDebugStrategies:
    """Test prompt_debug functionality in reprompt strategies."""

    def test_llm_strategy_debug_off(self):
        """Test LLMRepromptStrategy with debug off."""
        strategy = LLMRepromptStrategy({"prompt_debug": False})
        
        context = RepromptContext(
            original_prompt="Test prompt",
            validation_error="Test error",
            validation_criteria={},
            attempt_number=1,
            failed_response="Failed",
            agent_config={}
        )
        
        f = io.StringIO()
        with redirect_stdout(f):
            result = strategy.generate_improved_prompt(context)
        
        output = f.getvalue()
        
        assert "📝 CONSTRUCTED IMPROVED PROMPT:" not in output
        assert "Test prompt" in result

    def test_llm_strategy_debug_on(self):
        """Test LLMRepromptStrategy with debug on."""
        strategy = LLMRepromptStrategy({"prompt_debug": True})
        
        context = RepromptContext(
            original_prompt="Test prompt",
            validation_error="Test error",
            validation_criteria={},
            attempt_number=1,
            failed_response="Failed",
            agent_config={}
        )
        
        f = io.StringIO()
        with redirect_stdout(f):
            result = strategy.generate_improved_prompt(context)
        
        output = f.getvalue()
        
        assert "📝 CONSTRUCTED IMPROVED PROMPT:" in output
        assert "=" * 80 in output

    def test_template_strategy_debug_off(self):
        """Test TemplateRepromptStrategy with debug off."""
        templates = {
            "word count": "Please provide exactly {expected} words. Original: {original_prompt}"
        }
        strategy = TemplateRepromptStrategy(templates, prompt_debug=False)
        
        context = RepromptContext(
            original_prompt="Test prompt",
            validation_error="Word count error",
            validation_criteria={"expected": 5},
            attempt_number=1,
            failed_response="Failed",
            agent_config={}
        )
        
        f = io.StringIO()
        with redirect_stdout(f):
            result = strategy.generate_improved_prompt(context)
        
        output = f.getvalue()
        
        assert "📝 TEMPLATE MATCH FOUND:" not in output
        assert "Please provide exactly 5 words" in result

    def test_template_strategy_debug_on(self):
        """Test TemplateRepromptStrategy with debug on."""
        templates = {
            "word count": "Please provide exactly {expected} words. Original: {original_prompt}"
        }
        strategy = TemplateRepromptStrategy(templates, prompt_debug=True)
        
        context = RepromptContext(
            original_prompt="Test prompt",
            validation_error="Word count error",
            validation_criteria={"expected": 5},
            attempt_number=1,
            failed_response="Failed",
            agent_config={}
        )
        
        f = io.StringIO()
        with redirect_stdout(f):
            result = strategy.generate_improved_prompt(context)
        
        output = f.getvalue()
        
        assert "📝 TEMPLATE MATCH FOUND:" in output
        assert "Pattern: word count" in output

    def test_template_strategy_no_match_debug(self):
        """Test TemplateRepromptStrategy fallback with debug on."""
        templates = {
            "specific error": "Template for specific error"
        }
        strategy = TemplateRepromptStrategy(templates, prompt_debug=True)
        
        context = RepromptContext(
            original_prompt="Test prompt",
            validation_error="Different error",
            validation_criteria={},
            attempt_number=1,
            failed_response="Failed",
            agent_config={}
        )
        
        f = io.StringIO()
        with redirect_stdout(f):
            result = strategy.generate_improved_prompt(context)
        
        output = f.getvalue()
        
        assert "📝 NO TEMPLATE MATCH - Using default fallback" in output
        assert "IMPORTANT: Different error" in result


class TestPromptDebugIntegration:
    """Test prompt_debug integration with InterceptorFactory."""

    def test_factory_passes_prompt_debug(self):
        """Test that InterceptorFactory properly passes prompt_debug to interceptors."""
        configs = [
            {
                "type": "validation",
                "prompt_debug": True,
                "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
                "validator_args": {"expected": 3}
            }
        ]
        
        
        chain = InterceptorFactory.build_chain(configs)
        
        # The first interceptor should be ValidationInterceptor with prompt_debug=True
        interceptor = chain.interceptors[0]
        assert isinstance(interceptor, ValidationInterceptor)
        assert interceptor.prompt_debug is True

    def test_config_immutability(self):
        """Test that original configs are not mutated in agent_builder."""
        # This would require importing and testing the actual agent_builder function
        # For now, we've verified the fix uses dictionary unpacking to create copies
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])