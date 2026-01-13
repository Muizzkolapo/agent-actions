"""
Unit tests for reprompt validation UDF system.

Tests the decorator, registry, and validation function management.
"""

import pytest
from agent_actions.core.reprompt_validation import (
    reprompt_validation,
    get_validation_function,
    list_validation_functions,
    _VALIDATION_REGISTRY,
)


class TestRepromptValidationDecorator:
    """Tests for @reprompt_validation decorator."""

    def setup_method(self):
        """Clear registry before each test."""
        _VALIDATION_REGISTRY.clear()

    def test_decorator_registers_function(self):
        """Decorator should register function in global registry."""

        @reprompt_validation("Test message")
        def test_validator(response: dict) -> bool:
            return True

        assert "test_validator" in _VALIDATION_REGISTRY
        func, message = _VALIDATION_REGISTRY["test_validator"]
        assert func == test_validator
        assert message == "Test message"

    def test_decorator_stores_message(self):
        """Decorator should store feedback message."""
        feedback_msg = "Response must contain 'foo' field"

        @reprompt_validation(feedback_msg)
        def check_foo(response: dict) -> bool:
            return "foo" in response

        func, stored_message = _VALIDATION_REGISTRY["check_foo"]
        assert stored_message == feedback_msg

    def test_decorator_preserves_function_behavior(self):
        """Decorated function should still work normally."""

        @reprompt_validation("Test message")
        def check_value(response: dict) -> bool:
            return response.get("value", 0) > 10

        # Function should work normally
        assert check_value({"value": 15}) is True
        assert check_value({"value": 5}) is False
        assert check_value({}) is False

    def test_multiple_decorators_registered(self):
        """Multiple UDFs should coexist in registry."""

        @reprompt_validation("Check A")
        def validator_a(response: dict) -> bool:
            return "a" in response

        @reprompt_validation("Check B")
        def validator_b(response: dict) -> bool:
            return "b" in response

        assert len(_VALIDATION_REGISTRY) == 2
        assert "validator_a" in _VALIDATION_REGISTRY
        assert "validator_b" in _VALIDATION_REGISTRY

    def test_decorator_with_complex_validation(self):
        """Decorator should work with complex validation logic."""

        @reprompt_validation("Response must not contain forbidden words")
        def check_no_forbidden_words(response: dict) -> bool:
            forbidden = ["spam", "scam", "fake"]
            text = str(response).lower()
            return not any(word in text for word in forbidden)

        # Test the validation logic
        assert check_no_forbidden_words({"description": "This is valid"}) is True
        assert check_no_forbidden_words({"description": "This is spam"}) is False
        assert check_no_forbidden_words({"title": "Scam alert"}) is False


class TestGetValidationFunction:
    """Tests for get_validation_function()."""

    def setup_method(self):
        """Clear registry before each test."""
        _VALIDATION_REGISTRY.clear()

    def test_get_validation_function_success(self):
        """Should retrieve registered function and message."""

        @reprompt_validation("Must have name field")
        def check_name(response: dict) -> bool:
            return "name" in response

        func, message = get_validation_function("check_name")

        assert func == check_name
        assert message == "Must have name field"
        # Verify function works
        assert func({"name": "Alice"}) is True
        assert func({}) is False

    def test_get_validation_function_not_found(self):
        """Should raise ValueError if UDF not registered."""
        with pytest.raises(ValueError) as exc_info:
            get_validation_function("nonexistent_validator")

        assert "Validation UDF 'nonexistent_validator' not found" in str(exc_info.value)
        assert "Available:" in str(exc_info.value)

    def test_get_validation_function_shows_available(self):
        """Error message should list available UDFs."""

        @reprompt_validation("Check A")
        def validator_a(response: dict) -> bool:
            return True

        @reprompt_validation("Check B")
        def validator_b(response: dict) -> bool:
            return True

        with pytest.raises(ValueError) as exc_info:
            get_validation_function("nonexistent")

        error_msg = str(exc_info.value)
        assert "validator_a" in error_msg
        assert "validator_b" in error_msg


class TestListValidationFunctions:
    """Tests for list_validation_functions()."""

    def setup_method(self):
        """Clear registry before each test."""
        _VALIDATION_REGISTRY.clear()

    def test_list_empty_registry(self):
        """Should return empty list when no UDFs registered."""
        assert list_validation_functions() == []

    def test_list_validation_functions(self):
        """Should return list of all registered UDF names."""

        @reprompt_validation("Check A")
        def validator_a(response: dict) -> bool:
            return True

        @reprompt_validation("Check B")
        def validator_b(response: dict) -> bool:
            return True

        @reprompt_validation("Check C")
        def validator_c(response: dict) -> bool:
            return True

        functions = list_validation_functions()
        assert len(functions) == 3
        assert "validator_a" in functions
        assert "validator_b" in functions
        assert "validator_c" in functions


class TestValidationUDFBehavior:
    """Tests for actual validation UDF execution."""

    def setup_method(self):
        """Clear registry before each test."""
        _VALIDATION_REGISTRY.clear()

    def test_udf_returns_true(self):
        """UDF should return True for valid responses."""

        @reprompt_validation("Must be positive")
        def check_positive(response: dict) -> bool:
            return response.get("value", 0) > 0

        assert check_positive({"value": 10}) is True
        assert check_positive({"value": 1}) is True

    def test_udf_returns_false(self):
        """UDF should return False for invalid responses."""

        @reprompt_validation("Must be positive")
        def check_positive(response: dict) -> bool:
            return response.get("value", 0) > 0

        assert check_positive({"value": -5}) is False
        assert check_positive({"value": 0}) is False
        assert check_positive({}) is False

    def test_udf_handles_missing_fields(self):
        """UDF should handle missing fields gracefully."""

        @reprompt_validation("Must have required fields")
        def check_required_fields(response: dict) -> bool:
            required = ["name", "email", "age"]
            return all(field in response for field in required)

        assert check_required_fields({"name": "Alice", "email": "a@b.com", "age": 25}) is True
        assert check_required_fields({"name": "Alice", "email": "a@b.com"}) is False
        assert check_required_fields({}) is False

    def test_udf_raises_exception(self):
        """UDF that raises exception should propagate error."""

        @reprompt_validation("Must be valid")
        def buggy_validator(response: dict) -> bool:
            # Intentionally buggy - will raise KeyError
            return response["required_field"] == "value"

        with pytest.raises(KeyError):
            buggy_validator({"other_field": "value"})

    def test_udf_with_nested_dict_validation(self):
        """UDF should handle nested dictionary validation."""

        @reprompt_validation("Must have valid nested structure")
        def check_nested(response: dict) -> bool:
            if "user" not in response:
                return False
            user = response["user"]
            return isinstance(user, dict) and "name" in user and "id" in user

        assert check_nested({"user": {"name": "Alice", "id": 123}}) is True
        assert check_nested({"user": {"name": "Alice"}}) is False
        assert check_nested({"user": "not a dict"}) is False
        assert check_nested({}) is False

    def test_udf_with_complex_business_logic(self):
        """UDF should support complex business validation rules."""

        @reprompt_validation("Book classification must be valid")
        def check_book_classification(response: dict) -> bool:
            # Check BISAC code format
            bisac = response.get("primary_bisac_code", "")
            if not (isinstance(bisac, str) and len(bisac) == 9):
                return False

            # Check reasoning is not empty
            reasoning = response.get("classification_reasoning", "")
            if not reasoning or len(reasoning.strip()) < 10:
                return False

            return True

        # Valid
        assert (
            check_book_classification(
                {
                    "primary_bisac_code": "COM051010",
                    "classification_reasoning": "This book covers software design patterns extensively.",
                }
            )
            is True
        )

        # Invalid - bad BISAC format
        assert (
            check_book_classification(
                {
                    "primary_bisac_code": "COM051",
                    "classification_reasoning": "Valid reasoning here.",
                }
            )
            is False
        )

        # Invalid - reasoning too short
        assert (
            check_book_classification(
                {"primary_bisac_code": "COM051010", "classification_reasoning": "Too short"}
            )
            is False
        )


class TestRegistryIsolation:
    """Tests for registry isolation and cleanup."""

    def setup_method(self):
        """Clear registry before each test."""
        _VALIDATION_REGISTRY.clear()

    def test_registry_persists_across_calls(self):
        """Registry should persist across multiple get_validation_function calls."""

        @reprompt_validation("Test message")
        def test_validator(response: dict) -> bool:
            return True

        # Multiple retrievals should work
        func1, msg1 = get_validation_function("test_validator")
        func2, msg2 = get_validation_function("test_validator")

        assert func1 == func2
        assert msg1 == msg2

    def test_registry_can_be_cleared(self):
        """Registry should be clearable for testing."""

        @reprompt_validation("Test message")
        def test_validator(response: dict) -> bool:
            return True

        assert len(_VALIDATION_REGISTRY) == 1

        _VALIDATION_REGISTRY.clear()

        assert len(_VALIDATION_REGISTRY) == 0
        with pytest.raises(ValueError):
            get_validation_function("test_validator")


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def setup_method(self):
        """Clear registry before each test."""
        _VALIDATION_REGISTRY.clear()

    def test_empty_feedback_message(self):
        """Should allow empty feedback message (though not recommended)."""

        @reprompt_validation("")
        def validator_with_empty_message(response: dict) -> bool:
            return True

        func, message = get_validation_function("validator_with_empty_message")
        assert message == ""

    def test_unicode_feedback_message(self):
        """Should handle unicode in feedback messages."""

        @reprompt_validation("Response must not contain emoji 🚫")
        def check_no_emoji(response: dict) -> bool:
            text = str(response)
            return "🚫" not in text

        func, message = get_validation_function("check_no_emoji")
        assert "🚫" in message

    def test_very_long_feedback_message(self):
        """Should handle very long feedback messages."""
        long_message = "A" * 1000

        @reprompt_validation(long_message)
        def validator_with_long_message(response: dict) -> bool:
            return True

        func, message = get_validation_function("validator_with_long_message")
        assert len(message) == 1000

    def test_non_dict_response_handling(self):
        """UDF should handle non-dict responses (edge case)."""

        @reprompt_validation("Must be valid")
        def flexible_validator(response: dict) -> bool:
            # Handle case where response might not be a dict
            if not isinstance(response, dict):
                return False
            return "valid" in response

        # These should not crash
        assert flexible_validator({"valid": True}) is True
        assert flexible_validator("not a dict") is False
        assert flexible_validator(None) is False
        assert flexible_validator([]) is False
