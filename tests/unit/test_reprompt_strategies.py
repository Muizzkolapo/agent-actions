"""
Unit tests for reprompt strategies.

Tests LLMRepromptStrategy and TemplateRepromptStrategy.
"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.strategies.reprompt_strategy import (
    RepromptContext,
    RepromptStrategy,
    LLMRepromptStrategy,
    TemplateRepromptStrategy
)


class TestRepromptContext:
    """Test suite for RepromptContext dataclass."""

    def test_reprompt_context_creation(self):
        """Test creating RepromptContext with all fields."""
        context = RepromptContext(
            original_prompt="Write a story",
            validation_error="Too short",
            validation_criteria={"min_words": 100},
            attempt_number=2,
            failed_response="Once upon a time",
            agent_config={"model": "gpt-4"}
        )
        
        assert context.original_prompt == "Write a story"
        assert context.validation_error == "Too short"
        assert context.validation_criteria == {"min_words": 100}
        assert context.attempt_number == 2
        assert context.failed_response == "Once upon a time"
        assert context.agent_config == {"model": "gpt-4"}


class TestLLMRepromptStrategy:
    """Test suite for LLMRepromptStrategy."""

    @pytest.fixture
    def mock_agent_builder(self):
        """Mock the agent_builder module."""
        with patch('agent_actions.agents.base.agent_builder') as mock:
            mock.create_dynamic_agent.return_value = [{"content": "Improved prompt"}]
            yield mock

    def test_init_with_custom_template(self):
        """Test initialization with custom prompt template."""
        custom_template = "Custom template: {original_prompt}"
        strategy = LLMRepromptStrategy({"prompt_template": custom_template})
        
        assert strategy.prompt_template == custom_template

    def test_init_with_default_template(self):
        """Test initialization with default template."""
        strategy = LLMRepromptStrategy({})
        
        assert "You are an expert prompt engineer" in strategy.prompt_template
        assert "{original_prompt}" in strategy.prompt_template
        assert "{validation_error}" in strategy.prompt_template

    def test_init_with_llm_config(self):
        """Test initialization with LLM configuration."""
        config = {
            "model_vendor": "anthropic",
            "model_name": "claude-3",
            "temperature": 0.5
        }
        strategy = LLMRepromptStrategy(config)
        
        assert strategy.llm_config == config

    def test_generate_improved_prompt(self, mock_agent_builder):
        """Test generating improved prompt with LLM."""
        strategy = LLMRepromptStrategy({
            "model_vendor": "openai",
            "model_name": "gpt-4"
        })
        
        context = RepromptContext(
            original_prompt="Write a story",
            validation_error="Too short: expected 100 words, got 10",
            validation_criteria={"min_words": 100},
            attempt_number=1,
            failed_response="Short story",
            agent_config={}
        )
        
        result = strategy.generate_improved_prompt(context)
        
        assert result == "Improved prompt"
        
        # Verify agent_builder was called correctly
        mock_agent_builder.create_dynamic_agent.assert_called_once()
        call_args = mock_agent_builder.create_dynamic_agent.call_args
        
        agent_config = call_args[0][0]
        assert agent_config["model_vendor"] == "openai"
        assert agent_config["model_name"] == "gpt-4"
        assert agent_config["temperature"] == 0.7
        assert "Write a story" in agent_config["prompt"]
        assert "Too short: expected 100 words, got 10" in agent_config["prompt"]

    def test_generate_improved_prompt_response_formats(self, mock_agent_builder):
        """Test handling different response formats from LLM."""
        strategy = LLMRepromptStrategy({})
        context = RepromptContext(
            original_prompt="Test",
            validation_error="Error",
            validation_criteria={},
            attempt_number=1,
            failed_response="",
            agent_config={}
        )
        
        # Test list with dict containing 'content'
        mock_agent_builder.create_dynamic_agent.return_value = [{"content": "From content"}]
        assert strategy.generate_improved_prompt(context) == "From content"
        
        # Test list with dict containing 'text'
        mock_agent_builder.create_dynamic_agent.return_value = [{"text": "From text"}]
        assert strategy.generate_improved_prompt(context) == "From text"
        
        # Test list with string
        mock_agent_builder.create_dynamic_agent.return_value = ["Direct string"]
        assert strategy.generate_improved_prompt(context) == "Direct string"
        
        # Test non-list response
        mock_agent_builder.create_dynamic_agent.return_value = "Plain response"
        assert strategy.generate_improved_prompt(context) == "Plain response"
        
        # Test empty list
        mock_agent_builder.create_dynamic_agent.return_value = []
        assert strategy.generate_improved_prompt(context) == "[]"

    def test_prompt_template_formatting(self, mock_agent_builder):
        """Test that prompt template is correctly formatted."""
        template = (
            "Original: {original_prompt}\n"
            "Error: {validation_error}\n"
            "Criteria: {validation_criteria}\n"
            "Attempt: {attempt_number}\n"
            "Failed: {failed_response}"
        )
        
        strategy = LLMRepromptStrategy({"prompt_template": template})
        
        context = RepromptContext(
            original_prompt="Write code",
            validation_error="Missing tests",
            validation_criteria={"requires_tests": True},
            attempt_number=2,
            failed_response="def add(a, b): return a + b",
            agent_config={}
        )
        
        strategy.generate_improved_prompt(context)
        
        call_args = mock_agent_builder.create_dynamic_agent.call_args[0][0]
        prompt = call_args["prompt"]
        
        assert "Original: Write code" in prompt
        assert "Error: Missing tests" in prompt
        assert "Criteria: {'requires_tests': True}" in prompt
        assert "Attempt: 2" in prompt
        assert "Failed: def add(a, b): return a + b" in prompt


class TestTemplateRepromptStrategy:
    """Test suite for TemplateRepromptStrategy."""

    def test_init(self):
        """Test initialization with templates."""
        templates = {
            "too short": "Please write more: {original_prompt}",
            "missing keyword": "Include '{keyword}' in your response: {original_prompt}"
        }
        
        strategy = TemplateRepromptStrategy(templates)
        assert strategy.templates == templates

    def test_generate_improved_prompt_matching_template(self):
        """Test generating prompt when error matches a template."""
        templates = {
            "too short": "Please provide at least {min_words} words. {original_prompt}",
            "too long": "Keep it under {max_words} words. {original_prompt}"
        }
        
        strategy = TemplateRepromptStrategy(templates)
        
        context = RepromptContext(
            original_prompt="Write a summary",
            validation_error="Response too short",
            validation_criteria={"min_words": 50},
            attempt_number=1,
            failed_response="Brief summary",
            agent_config={}
        )
        
        result = strategy.generate_improved_prompt(context)
        assert result == "Please provide at least 50 words. Write a summary"

    def test_generate_improved_prompt_no_matching_template(self):
        """Test generating prompt when no template matches."""
        templates = {
            "too short": "Write more",
            "too long": "Write less"
        }
        
        strategy = TemplateRepromptStrategy(templates)
        
        context = RepromptContext(
            original_prompt="Write something",
            validation_error="Invalid format",
            validation_criteria={},
            attempt_number=1,
            failed_response="",
            agent_config={}
        )
        
        result = strategy.generate_improved_prompt(context)
        assert result == "Write something\n\nIMPORTANT: Invalid format"

    def test_template_pattern_matching_case_insensitive(self):
        """Test that pattern matching is case insensitive."""
        templates = {
            "missing keywords": "Include keywords: {original_prompt}"
        }
        
        strategy = TemplateRepromptStrategy(templates)
        
        context = RepromptContext(
            original_prompt="Write text",
            validation_error="MISSING KEYWORDS: python, testing",
            validation_criteria={},
            attempt_number=1,
            failed_response="",
            agent_config={}
        )
        
        result = strategy.generate_improved_prompt(context)
        assert result == "Include keywords: Write text"

    def test_template_with_validation_criteria(self):
        """Test template using validation criteria values."""
        templates = {
            "word count": "Write exactly {expected} words. {original_prompt}"
        }
        
        strategy = TemplateRepromptStrategy(templates)
        
        context = RepromptContext(
            original_prompt="Describe Python",
            validation_error="Wrong word count",
            validation_criteria={"expected": 100},
            attempt_number=1,
            failed_response="",
            agent_config={}
        )
        
        result = strategy.generate_improved_prompt(context)
        assert result == "Write exactly 100 words. Describe Python"

    def test_multiple_patterns_first_match_wins(self):
        """Test that first matching pattern is used."""
        templates = {
            "too": "First template: {original_prompt}",
            "too short": "Second template: {original_prompt}",
            "short": "Third template: {original_prompt}"
        }
        
        strategy = TemplateRepromptStrategy(templates)
        
        context = RepromptContext(
            original_prompt="Test",
            validation_error="Response too short",
            validation_criteria={},
            attempt_number=1,
            failed_response="",
            agent_config={}
        )
        
        result = strategy.generate_improved_prompt(context)
        # "too" appears first in "too short" and should match first
        assert result == "First template: Test"

    def test_empty_templates(self):
        """Test with empty templates dictionary."""
        strategy = TemplateRepromptStrategy({})
        
        context = RepromptContext(
            original_prompt="Write something",
            validation_error="Some error",
            validation_criteria={},
            attempt_number=1,
            failed_response="",
            agent_config={}
        )
        
        result = strategy.generate_improved_prompt(context)
        assert result == "Write something\n\nIMPORTANT: Some error"

    def test_template_missing_placeholders(self):
        """Test template that doesn't use all available placeholders."""
        templates = {
            "error": "Just try again"  # No placeholders
        }
        
        strategy = TemplateRepromptStrategy(templates)
        
        context = RepromptContext(
            original_prompt="Original",
            validation_error="Some error",
            validation_criteria={"key": "value"},
            attempt_number=1,
            failed_response="",
            agent_config={}
        )
        
        result = strategy.generate_improved_prompt(context)
        assert result == "Just try again"