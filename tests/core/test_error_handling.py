"""Tests for the error handling framework."""
import logging
import pytest

from agent_actions.core.errors import (
    handle_errors,
    ValidationError,
    ResourceNotFoundError
)

# Test Type 1: New Recoverable Errors
def test_local_recovery():
    def process_data(data):
        if data.get('value') is None:
            data['value'] = 0
        return data['value'] + 10
    
    assert process_data({}) == 10
    assert process_data({'value': 5}) == 15

# Test Type 2: Bubbled-Up Recoverable Errors
def test_handle_errors_decorator():
    @handle_errors(ValueError, fallback_value=0)
    def divide(a, b):
        return a / b
    
    assert divide(10, 2) == 5
    assert divide(10, 0) == 0  # Falls back to 0

# Test Type 3: New Non-Recoverable Errors
def test_validation_error():
    def validate_positive(value):
        if value <= 0:
            raise ValidationError("Value must be positive")
        return value
    
    with pytest.raises(ValidationError):
        validate_positive(-1)
    
    assert validate_positive(1) == 1

# Test Type 4: Bubbled-Up Non-Recoverable Errors
def test_error_propagation():
    def inner_function():
        raise ResourceNotFoundError("Resource not found")
    
    def outer_function():
        inner_function()
    
    with pytest.raises(ResourceNotFoundError):
        outer_function() 