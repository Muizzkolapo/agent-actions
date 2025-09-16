"""
Unit tests for ValidationInterceptor.

Tests validation logic, error handling, and integration with validator functions.
"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.agents.interceptors.validation_interceptor import ValidationInterceptor
from agent_actions.agents.interceptors.base import InterceptorResult


class TestValidationInterceptor:
    """Test suite for ValidationInterceptor."""

    @pytest.fixture
    def interceptor(self):
        """Create a ValidationInterceptor instance."""
        return ValidationInterceptor()

    @pytest.fixture
    def mock_validator(self):
        """Create a mock validator function."""
        validator = Mock()
        validator.return_value = (True, None)
        return validator

    def test_init(self, interceptor):
        """Test interceptor initialization."""
        assert interceptor.validator_function is None
        assert interceptor.validator_args == {}
        assert interceptor.on_failure == "retry"

    def test_configure_with_valid_validator_function(self, interceptor):
        """Test configuration with a valid validator function."""
        config = {
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 10},
            "on_failure": "fail"
        }
        interceptor.configure(config)
        
        assert interceptor.validator_function == "agent_actions.validators.builtin_functions.word_count_validator"
        assert interceptor.validator_args == {"expected": 10}
        assert interceptor.on_failure == "fail"

    def test_configure_with_missing_validator_function(self, interceptor):
        """Test configuration with missing validator function."""
        config = {"validator_args": {"expected": 10}}
        
        with pytest.raises(ValueError, match="validator_function is required"):
            interceptor.configure(config)

    def test_intercept_without_validator_function(self, interceptor):
        """Test intercept when no validator function is configured."""
        result = interceptor.intercept("test response", {})
        
        assert result.continue_processing is True
        assert result.retry_context is None

    def test_intercept_validation_success(self, interceptor):
        """Test intercept when validation passes."""
        # Use the real word_count_validator
        interceptor.validator_function = "agent_actions.validators.builtin_functions.word_count_validator"
        interceptor.validator_args = {"expected": 2}
        
        result = interceptor.intercept("test response", {})
        
        assert result.continue_processing is True
        assert result.retry_context is None

    def test_intercept_validation_failure_retry(self, interceptor):
        """Test intercept when validation fails with retry action."""
        # Use the real word_count_validator with impossible expectation
        interceptor.validator_function = "agent_actions.validators.builtin_functions.word_count_validator"
        interceptor.validator_args = {"expected": 10}
        interceptor.on_failure = "retry"
        
        response = {"content": "test response"}  # 2 words, expects 10
        result = interceptor.intercept(response, {})
        
        assert result.continue_processing is False
        assert result.retry_context is not None
        assert "Expected 10 words, got 2" in result.retry_context["validation_error"]
        assert result.retry_context["validator_function"] == "agent_actions.validators.builtin_functions.word_count_validator"
        assert result.retry_context["validator_args"] == {"expected": 10}
        assert result.retry_context["failed_response"] == response

    def test_intercept_validation_failure_fail(self, interceptor):
        """Test intercept when validation fails with fail action."""
        interceptor.validator_function = "agent_actions.validators.builtin_functions.word_count_validator"
        interceptor.validator_args = {"expected": 10}
        interceptor.on_failure = "fail"
        
        with pytest.raises(ValueError, match="Validation failed: Expected 10 words, got 2"):
            interceptor.intercept("test response", {})

    def test_intercept_validation_failure_continue(self, interceptor):
        """Test intercept when validation fails with continue action."""
        interceptor.validator_function = "agent_actions.validators.builtin_functions.word_count_validator"
        interceptor.validator_args = {"expected": 10}
        interceptor.on_failure = "continue"
        
        result = interceptor.intercept("test response", {})
        
        assert result.continue_processing is True
        assert "Expected 10 words, got 2" in result.metadata["validation_warning"]

    @pytest.mark.parametrize("response,expected_content", [
        # List with dict containing 'content'
        ([{"content": "test content"}], "test content"),
        # List with dict containing 'text'
        ([{"text": "test text"}], "test text"),
        # List with dict containing both (content takes precedence)
        ([{"content": "content", "text": "text"}], "content"),
        # List with string
        (["string content"], "string content"),
        # Dict with 'content'
        ({"content": "dict content"}, "dict content"),
        # Dict with 'text'
        ({"text": "dict text"}, "dict text"),
        # String response
        ("plain string", "plain string"),
        # Number response
        (42, "42"),
        # Empty list
        ([], "[]"),
    ])
    def test_extract_content(self, interceptor, response, expected_content):
        """Test content extraction from various response formats."""
        content = interceptor._extract_content(response)
        assert content == expected_content

    def test_full_validation_flow_with_word_count(self, interceptor):
        """Test full validation flow with the built-in word_count validator function."""
        config = {
            "validator_function": "agent_actions.validators.builtin_functions.word_count_validator",
            "validator_args": {"expected": 5},
            "on_failure": "retry"
        }
        
        # Configure with real validator function
        interceptor.configure(config)
        
        # Test success case
        success_response = {"content": "This is exactly five words"}
        result = interceptor.intercept(success_response, {})
        assert result.continue_processing is True
        
        # Test failure case
        failure_response = {"content": "Too few words"}
        result = interceptor.intercept(failure_response, {})
        assert result.continue_processing is False
        assert "Expected 5 words, got 3" in result.retry_context["validation_error"]

    def test_validator_function_with_kwargs(self, interceptor):
        """Test that validator function is called with configured arguments."""
        # Use char_count_validator which accepts min_chars and max_chars
        interceptor.validator_function = "agent_actions.validators.builtin_functions.char_count_validator"
        interceptor.validator_args = {"min_chars": 5, "max_chars": 100}
        
        result = interceptor.intercept("test content", {})
        
        # This should pass because "test content" has 12 chars, within the 5-100 range
        assert result.continue_processing is True
        assert result.retry_context is None

    def test_empty_response_handling(self, interceptor):
        """Test handling of empty responses."""
        interceptor.validator_function = "agent_actions.validators.builtin_functions.word_count_validator"
        interceptor.validator_args = {"expected": 5}
        interceptor.on_failure = "retry"
        
        # Empty dict
        result = interceptor.intercept({}, {})
        assert result.continue_processing is False
        assert "Expected 5 words, got 0" in result.retry_context["validation_error"]
        
        # None values in dict
        result = interceptor.intercept({"content": None}, {})
        assert result.continue_processing is False
        assert "Expected 5 words, got 0" in result.retry_context["validation_error"]

    def test_invalid_function_handling(self, interceptor):
        """Test handling of invalid validator function."""
        interceptor.validator_function = "nonexistent.module.function"
        interceptor.on_failure = "retry"
        
        result = interceptor.intercept("test content", {})
        
        assert result.continue_processing is False
        assert "Validator function error" in result.retry_context["validation_error"]