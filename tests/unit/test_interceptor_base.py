"""
Unit tests for interceptor base classes.

Tests InterceptorResult, ResponseInterceptor, and InterceptorChain.
"""

import pytest
from unittest.mock import Mock
from agent_actions.agents.interceptors.base import (
    InterceptorResult,
    ResponseInterceptor,
    InterceptorChain
)


class TestInterceptorResult:
    """Test suite for InterceptorResult dataclass."""

    def test_default_values(self):
        """Test InterceptorResult with default values."""
        result = InterceptorResult()
        
        assert result.continue_processing is True
        assert result.modified_response is None
        assert result.retry_context is None
        assert result.metadata is None

    def test_custom_values(self):
        """Test InterceptorResult with custom values."""
        result = InterceptorResult(
            continue_processing=False,
            modified_response="Modified",
            retry_context={"retry": True},
            metadata={"key": "value"}
        )
        
        assert result.continue_processing is False
        assert result.modified_response == "Modified"
        assert result.retry_context == {"retry": True}
        assert result.metadata == {"key": "value"}


class MockInterceptor(ResponseInterceptor):
    """Mock interceptor for testing."""
    
    def __init__(self, result: InterceptorResult):
        self.result = result
        self.intercepted = False
        self.configure_called = False
        
    def intercept(self, response, context):
        self.intercepted = True
        self.last_response = response
        self.last_context = context
        return self.result
        
    def configure(self, config):
        self.configure_called = True
        self.config = config


class TestInterceptorChain:
    """Test suite for InterceptorChain."""

    def test_empty_chain(self):
        """Test chain with no interceptors."""
        chain = InterceptorChain([])
        
        result = chain.process("response", {})
        
        assert result.continue_processing is True
        assert result.modified_response == "response"

    def test_single_interceptor_continue(self):
        """Test chain with single interceptor that continues."""
        interceptor = MockInterceptor(InterceptorResult(continue_processing=True))
        chain = InterceptorChain([interceptor])
        
        result = chain.process("response", {"key": "value"})
        
        assert interceptor.intercepted is True
        assert interceptor.last_response == "response"
        assert interceptor.last_context == {"key": "value"}
        assert result.continue_processing is True
        assert result.modified_response == "response"

    def test_single_interceptor_stop(self):
        """Test chain with single interceptor that stops processing."""
        interceptor = MockInterceptor(InterceptorResult(
            continue_processing=False,
            metadata={"stopped": True}
        ))
        chain = InterceptorChain([interceptor])
        
        result = chain.process("response", {})
        
        assert result.continue_processing is False
        assert result.metadata == {"stopped": True}

    def test_single_interceptor_modify(self):
        """Test chain with single interceptor that modifies response."""
        interceptor = MockInterceptor(InterceptorResult(
            continue_processing=True,
            modified_response="Modified response"
        ))
        chain = InterceptorChain([interceptor])
        
        result = chain.process("Original response", {})
        
        assert result.continue_processing is True
        assert result.modified_response == "Modified response"

    def test_single_interceptor_retry(self):
        """Test chain with single interceptor that requests retry."""
        interceptor = MockInterceptor(InterceptorResult(
            continue_processing=False,
            retry_context={"retry": True, "reason": "validation failed"}
        ))
        chain = InterceptorChain([interceptor])
        
        result = chain.process("response", {})
        
        assert result.continue_processing is False
        assert result.retry_context == {"retry": True, "reason": "validation failed"}

    def test_multiple_interceptors_all_continue(self):
        """Test chain with multiple interceptors that all continue."""
        interceptor1 = MockInterceptor(InterceptorResult(continue_processing=True))
        interceptor2 = MockInterceptor(InterceptorResult(continue_processing=True))
        interceptor3 = MockInterceptor(InterceptorResult(continue_processing=True))
        
        chain = InterceptorChain([interceptor1, interceptor2, interceptor3])
        
        result = chain.process("response", {})
        
        assert all(i.intercepted for i in [interceptor1, interceptor2, interceptor3])
        assert result.continue_processing is True

    def test_multiple_interceptors_second_stops(self):
        """Test chain where second interceptor stops processing."""
        interceptor1 = MockInterceptor(InterceptorResult(continue_processing=True))
        interceptor2 = MockInterceptor(InterceptorResult(continue_processing=False))
        interceptor3 = MockInterceptor(InterceptorResult(continue_processing=True))
        
        chain = InterceptorChain([interceptor1, interceptor2, interceptor3])
        
        result = chain.process("response", {})
        
        assert interceptor1.intercepted is True
        assert interceptor2.intercepted is True
        assert interceptor3.intercepted is False  # Should not be called
        assert result.continue_processing is False

    def test_response_modification_chain(self):
        """Test response modifications are chained through interceptors."""
        interceptor1 = MockInterceptor(InterceptorResult(
            continue_processing=True,
            modified_response="Modified by 1"
        ))
        interceptor2 = MockInterceptor(InterceptorResult(
            continue_processing=True,
            modified_response="Modified by 2"
        ))
        interceptor3 = MockInterceptor(InterceptorResult(
            continue_processing=True
            # No modification
        ))
        
        chain = InterceptorChain([interceptor1, interceptor2, interceptor3])
        
        result = chain.process("Original", {})
        
        # Check each interceptor received the previous modification
        assert interceptor1.last_response == "Original"
        assert interceptor2.last_response == "Modified by 1"
        assert interceptor3.last_response == "Modified by 2"
        
        assert result.modified_response == "Modified by 2"

    def test_retry_context_stops_chain(self):
        """Test that retry context immediately stops the chain."""
        interceptor1 = MockInterceptor(InterceptorResult(
            continue_processing=True
        ))
        interceptor2 = MockInterceptor(InterceptorResult(
            continue_processing=True,
            retry_context={"retry": True}
        ))
        interceptor3 = MockInterceptor(InterceptorResult(
            continue_processing=True
        ))
        
        chain = InterceptorChain([interceptor1, interceptor2, interceptor3])
        
        result = chain.process("response", {})
        
        assert interceptor1.intercepted is True
        assert interceptor2.intercepted is True
        assert interceptor3.intercepted is False  # Should not be called
        assert result.retry_context == {"retry": True}

    def test_metadata_preserved_on_stop(self):
        """Test that metadata is preserved when processing stops."""
        interceptor = MockInterceptor(InterceptorResult(
            continue_processing=False,
            modified_response="Final response",
            metadata={"reason": "limit reached", "count": 5}
        ))
        
        chain = InterceptorChain([interceptor])
        
        result = chain.process("response", {})
        
        assert result.continue_processing is False
        assert result.modified_response == "Final response"
        assert result.metadata == {"reason": "limit reached", "count": 5}

    def test_complex_scenario(self):
        """Test complex scenario with multiple interceptors and modifications."""
        # First interceptor modifies and continues
        interceptor1 = MockInterceptor(InterceptorResult(
            continue_processing=True,
            modified_response={"content": "Step 1", "original": "data"}
        ))
        
        # Second interceptor adds metadata and continues
        interceptor2 = MockInterceptor(InterceptorResult(
            continue_processing=True,
            metadata={"processed_by": "interceptor2"}
        ))
        
        # Third interceptor modifies and stops with retry
        interceptor3 = MockInterceptor(InterceptorResult(
            continue_processing=False,
            modified_response={"content": "Step 3", "previous": "Step 1"},
            retry_context={"reason": "validation_failed", "attempt": 1}
        ))
        
        chain = InterceptorChain([interceptor1, interceptor2, interceptor3])
        
        result = chain.process({"content": "Original"}, {"request_id": "123"})
        
        # Verify all interceptors were called with correct inputs
        assert interceptor1.last_response == {"content": "Original"}
        assert interceptor2.last_response == {"content": "Step 1", "original": "data"}
        assert interceptor3.last_response == {"content": "Step 1", "original": "data"}
        
        # Verify final result
        assert result.continue_processing is False
        assert result.retry_context == {"reason": "validation_failed", "attempt": 1}
        # Note: when retry_context is set, modified_response might not be in the result