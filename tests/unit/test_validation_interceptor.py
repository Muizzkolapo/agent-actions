"""
Unit tests for ValidationInterceptor.

Tests validation logic, error handling, and integration with ValidatorRegistry.
"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.interceptors.validation_interceptor import ValidationInterceptor
from agent_actions.interceptors.base import InterceptorResult
from agent_actions.validators.registry import ValidatorRegistry


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
        assert interceptor.validator_name is None
        assert interceptor.validator_args == {}
        assert interceptor.on_failure == "retry"
        assert interceptor.validator_func is None

    def test_configure_with_valid_validator(self, interceptor, mock_validator):
        """Test configuration with a valid validator."""
        with patch.object(ValidatorRegistry, 'get', return_value=mock_validator):
            config = {
                "validator": "word_count",
                "validator_args": {"expected": 10},
                "on_failure": "fail"
            }
            interceptor.configure(config)
            
            assert interceptor.validator_name == "word_count"
            assert interceptor.validator_args == {"expected": 10}
            assert interceptor.on_failure == "fail"
            assert interceptor.validator_func == mock_validator

    def test_configure_with_invalid_validator(self, interceptor):
        """Test configuration with an invalid validator."""
        with patch.object(ValidatorRegistry, 'get', return_value=None):
            config = {"validator": "non_existent"}
            
            with pytest.raises(ValueError, match="Unknown validator: non_existent"):
                interceptor.configure(config)

    def test_intercept_without_validator(self, interceptor):
        """Test intercept when no validator is configured."""
        result = interceptor.intercept("test response", {})
        
        assert result.continue_processing is True
        assert result.retry_context is None

    def test_intercept_validation_success(self, interceptor, mock_validator):
        """Test intercept when validation passes."""
        mock_validator.return_value = (True, None)
        interceptor.validator_func = mock_validator
        
        result = interceptor.intercept("test response", {})
        
        assert result.continue_processing is True
        assert result.retry_context is None
        mock_validator.assert_called_once_with("test response")

    def test_intercept_validation_failure_retry(self, interceptor, mock_validator):
        """Test intercept when validation fails with retry action."""
        mock_validator.return_value = (False, "Validation failed")
        interceptor.validator_func = mock_validator
        interceptor.on_failure = "retry"
        interceptor.validator_name = "test_validator"
        interceptor.validator_args = {"arg": "value"}
        
        response = {"content": "test response"}
        result = interceptor.intercept(response, {})
        
        assert result.continue_processing is False
        assert result.retry_context == {
            "validation_error": "Validation failed",
            "validator_name": "test_validator",
            "validator_args": {"arg": "value"},
            "failed_response": response
        }

    def test_intercept_validation_failure_fail(self, interceptor, mock_validator):
        """Test intercept when validation fails with fail action."""
        mock_validator.return_value = (False, "Validation failed")
        interceptor.validator_func = mock_validator
        interceptor.on_failure = "fail"
        
        with pytest.raises(ValueError, match="Validation failed: Validation failed"):
            interceptor.intercept("test response", {})

    def test_intercept_validation_failure_continue(self, interceptor, mock_validator):
        """Test intercept when validation fails with continue action."""
        mock_validator.return_value = (False, "Validation warning")
        interceptor.validator_func = mock_validator
        interceptor.on_failure = "continue"
        
        result = interceptor.intercept("test response", {})
        
        assert result.continue_processing is True
        assert result.metadata == {"validation_warning": "Validation warning"}

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
        """Test full validation flow with the built-in word_count validator."""
        config = {
            "validator": "word_count",
            "validator_args": {"expected": 5},
            "on_failure": "retry"
        }
        
        # Configure with real validator
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

    def test_validator_with_kwargs(self, interceptor, mock_validator):
        """Test that validator is called with configured arguments."""
        mock_validator.return_value = (True, None)
        interceptor.validator_func = mock_validator
        interceptor.validator_args = {"min_length": 10, "max_length": 100}
        
        interceptor.intercept("test", {})
        
        mock_validator.assert_called_once_with("test", min_length=10, max_length=100)

    def test_empty_response_handling(self, interceptor, mock_validator):
        """Test handling of empty responses."""
        mock_validator.return_value = (False, "Empty response")
        interceptor.validator_func = mock_validator
        
        # Empty dict
        result = interceptor.intercept({}, {})
        mock_validator.assert_called_with("")
        
        # None values in dict
        result = interceptor.intercept({"content": None}, {})
        mock_validator.assert_called_with("")