"""
Unit tests for RepromptService.

Tests the core reprompt orchestration logic including validation
loops, feedback generation, and recovery metadata.
"""

import pytest
from unittest.mock import Mock, call
from agent_actions.processing.recovery.reprompt import (
    RepromptService,
    RepromptResult,
    create_reprompt_service_from_config,
)
from agent_actions.processing.recovery.validation import (
    reprompt_validation,
    _VALIDATION_REGISTRY,
)


class TestRepromptServiceInit:
    """Tests for RepromptService initialization."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be valid")
        def test_validator(response: dict) -> bool:
            return response.get("valid", False)

    def test_init_with_valid_udf(self):
        """Should initialize with registered UDF."""
        service = RepromptService(
            validation_name="test_validator", max_attempts=2, on_exhausted="return_last"
        )

        assert service.validation_name == "test_validator"
        assert service.max_attempts == 2
        assert service.on_exhausted == "return_last"
        assert service.validation_func is not None
        assert service.feedback_message == "Must be valid"

    def test_init_with_defaults(self):
        """Should use default values for optional params."""
        service = RepromptService(validation_name="test_validator")

        assert service.max_attempts == 2  # Default
        assert service.on_exhausted == "return_last"  # Default

    def test_init_with_nonexistent_udf(self):
        """Should raise ValueError if UDF not registered."""
        with pytest.raises(ValueError) as exc_info:
            RepromptService(validation_name="nonexistent_validator")

        assert "Validation UDF 'nonexistent_validator' not found" in str(exc_info.value)


class TestRepromptServiceValidationPasses:
    """Tests for cases where validation passes."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be positive")
        def check_positive(response: dict) -> bool:
            return response.get("value", 0) > 0

    def test_validation_passes_first_attempt(self):
        """Should return immediately when validation passes on first attempt."""
        service = RepromptService(validation_name="check_positive", max_attempts=3)

        # Mock LLM operation that returns valid response
        llm_operation = Mock(return_value=({"value": 10}, True))

        result = service.execute(
            llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
        )

        # Should only call LLM once
        assert llm_operation.call_count == 1

        # Check result
        assert result.response == {"value": 10}
        assert result.attempts == 1
        assert result.passed is True
        assert result.validation_name == "check_positive"
        assert result.exhausted is False

    def test_validation_passes_after_retry(self):
        """Should reprompt until validation passes."""
        service = RepromptService(validation_name="check_positive", max_attempts=3)

        # Mock LLM operation: fails twice, then succeeds
        llm_operation = Mock(
            side_effect=[
                ({"value": -5}, True),  # Invalid
                ({"value": 0}, True),  # Invalid
                ({"value": 15}, True),  # Valid
            ]
        )

        result = service.execute(
            llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
        )

        # Should call LLM 3 times
        assert llm_operation.call_count == 3

        # Check result
        assert result.response == {"value": 15}
        assert result.attempts == 3
        assert result.passed is True
        assert result.exhausted is False


class TestRepromptServiceExhaustion:
    """Tests for cases where validation exhausts attempts."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be positive")
        def check_positive(response: dict) -> bool:
            return response.get("value", 0) > 0

    def test_exhausted_return_last(self):
        """on_exhausted=return_last should return last response."""
        service = RepromptService(
            validation_name="check_positive", max_attempts=2, on_exhausted="return_last"
        )

        # Mock LLM operation: always returns invalid
        llm_operation = Mock(
            side_effect=[
                ({"value": -5}, True),
                ({"value": -10}, True),
            ]
        )

        result = service.execute(
            llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
        )

        # Should call LLM max_attempts times
        assert llm_operation.call_count == 2

        # Check result
        assert result.response == {"value": -10}  # Last response
        assert result.attempts == 2
        assert result.passed is False
        assert result.exhausted is True

    def test_exhausted_raise(self):
        """on_exhausted=raise should raise RuntimeError."""
        service = RepromptService(
            validation_name="check_positive", max_attempts=2, on_exhausted="raise"
        )

        # Mock LLM operation: always returns invalid
        llm_operation = Mock(
            side_effect=[
                ({"value": -5}, True),
                ({"value": -10}, True),
            ]
        )

        with pytest.raises(RuntimeError) as exc_info:
            service.execute(
                llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
            )

        assert "Reprompt validation exhausted after 2 attempts" in str(exc_info.value)
        assert "check_positive" in str(exc_info.value)

        # Should still call LLM max_attempts times
        assert llm_operation.call_count == 2


class TestRepromptServiceGuardSkip:
    """Tests for cases where guards skip execution."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be valid")
        def test_validator(response: dict) -> bool:
            return response.get("valid", False)

    def test_guard_skip_bypasses_validation(self):
        """When LLM returns executed=False (guard skip), should bypass validation."""
        service = RepromptService(validation_name="test_validator", max_attempts=2)

        # Mock LLM operation: guard skipped (executed=False)
        llm_operation = Mock(return_value=({"passthrough": "data"}, False))

        result = service.execute(
            llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
        )

        # Should only call LLM once
        assert llm_operation.call_count == 1

        # Check result - no validation attempts
        assert result.response == {"passthrough": "data"}
        assert result.attempts == 0  # No validation attempts
        assert result.passed is True  # Treat as pass
        assert result.exhausted is False


class TestFeedbackMessageGeneration:
    """Tests for feedback message generation."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Response must contain 'name' field")
        def check_name(response: dict) -> bool:
            return "name" in response

    def test_feedback_message_format(self):
        """Should generate properly formatted feedback message."""
        service = RepromptService(validation_name="check_name", max_attempts=2)

        failed_response = {"email": "test@example.com"}
        feedback = service._build_feedback_message(failed_response)

        # Check format
        assert "---" in feedback
        assert "Your response failed validation:" in feedback
        assert "Response must contain 'name' field" in feedback
        assert "Your response:" in feedback
        assert '"email": "test@example.com"' in feedback
        assert "Please correct and respond again." in feedback

    def test_feedback_with_complex_response(self):
        """Should handle complex nested responses in feedback."""
        service = RepromptService(validation_name="check_name", max_attempts=2)

        failed_response = {
            "user": {"email": "test@example.com", "preferences": ["dark_mode", "notifications"]},
            "timestamp": "2024-01-13T12:00:00Z",
        }

        feedback = service._build_feedback_message(failed_response)

        # Should contain JSON representation
        assert '"user"' in feedback
        assert '"email"' in feedback
        assert '"preferences"' in feedback
        assert '"timestamp"' in feedback

    def test_feedback_with_non_serializable_response(self):
        """Should fallback to str() for non-JSON-serializable responses."""
        service = RepromptService(validation_name="check_name", max_attempts=2)

        # Mock a response with non-serializable object
        class CustomObject:
            def __str__(self):
                return "CustomObject(id=123)"

        failed_response = {"obj": CustomObject()}

        # Should not crash, fallback to str()
        feedback = service._build_feedback_message(failed_response)
        assert "Your response:" in feedback


class TestValidationUDFErrors:
    """Tests for handling validation UDF errors."""

    def setup_method(self):
        """Clear registry and register buggy UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be valid")
        def buggy_validator(response: dict) -> bool:
            # Intentionally buggy - raises KeyError
            return response["required_field"] == "value"

    def test_udf_exception_treated_as_invalid(self):
        """When UDF raises exception, should treat as validation failure."""
        service = RepromptService(
            validation_name="buggy_validator", max_attempts=2, on_exhausted="return_last"
        )

        # Mock LLM operation
        llm_operation = Mock(
            side_effect=[
                ({"other_field": "value"}, True),
                ({"other_field": "value2"}, True),
            ]
        )

        result = service.execute(
            llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
        )

        # Should exhaust attempts (UDF always raises)
        assert llm_operation.call_count == 2
        assert result.attempts == 2
        assert result.passed is False
        assert result.exhausted is True


class TestCreateRepromptServiceFromConfig:
    """Tests for create_reprompt_service_from_config factory function."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be valid")
        def test_validator(response: dict) -> bool:
            return response.get("valid", False)

    def test_create_with_full_config(self):
        """Should create service from complete config."""
        config = {"validation": "test_validator", "max_attempts": 3, "on_exhausted": "raise"}

        service = create_reprompt_service_from_config(config)

        assert service is not None
        assert service.validation_name == "test_validator"
        assert service.max_attempts == 3
        assert service.on_exhausted == "raise"

    def test_create_with_minimal_config(self):
        """Should create service with defaults from minimal config."""
        config = {"validation": "test_validator"}

        service = create_reprompt_service_from_config(config)

        assert service is not None
        assert service.validation_name == "test_validator"
        assert service.max_attempts == 2  # Default
        assert service.on_exhausted == "return_last"  # Default

    def test_create_with_none_config(self):
        """Should return None when config is None."""
        service = create_reprompt_service_from_config(None)
        assert service is None

    def test_create_with_empty_config(self):
        """Should return None when config is empty dict."""
        service = create_reprompt_service_from_config({})
        assert service is None


class TestRepromptAttemptTracking:
    """Tests for correct attempt tracking across validation loops."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must match pattern")
        def check_pattern(response: dict) -> bool:
            return response.get("status") == "success"

    def test_attempt_tracking_single_pass(self):
        """Should track 1 attempt when passing first try."""
        service = RepromptService(validation_name="check_pattern", max_attempts=3)

        llm_operation = Mock(return_value=({"status": "success"}, True))

        result = service.execute(
            llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
        )

        assert result.attempts == 1

    def test_attempt_tracking_multiple_tries(self):
        """Should track correct number of attempts."""
        service = RepromptService(validation_name="check_pattern", max_attempts=5)

        # Fails 3 times, then succeeds
        llm_operation = Mock(
            side_effect=[
                ({"status": "pending"}, True),
                ({"status": "failed"}, True),
                ({"status": "retry"}, True),
                ({"status": "success"}, True),
            ]
        )

        result = service.execute(
            llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
        )

        assert result.attempts == 4
        assert result.passed is True

    def test_attempt_tracking_exhausted(self):
        """Should track all attempts when exhausted."""
        service = RepromptService(validation_name="check_pattern", max_attempts=3)

        # Always fails
        llm_operation = Mock(
            side_effect=[
                ({"status": "pending"}, True),
                ({"status": "failed"}, True),
                ({"status": "retry"}, True),
            ]
        )

        result = service.execute(
            llm_operation=llm_operation,
            original_prompt="Test prompt",
            context="test_action",
            on_exhausted="return_last",
        )

        assert result.attempts == 3
        assert result.passed is False
        assert result.exhausted is True


class TestRepromptServiceEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be valid")
        def test_validator(response: dict) -> bool:
            return response.get("valid", False)

    def test_max_attempts_one(self):
        """Should work with max_attempts=1 (no reprompt, just validate)."""
        service = RepromptService(
            validation_name="test_validator", max_attempts=1, on_exhausted="return_last"
        )

        # Mock LLM operation: returns invalid
        llm_operation = Mock(return_value=({"valid": False}, True))

        result = service.execute(
            llm_operation=llm_operation, original_prompt="Test prompt", context="test_action"
        )

        # Should only call once
        assert llm_operation.call_count == 1
        assert result.attempts == 1
        assert result.passed is False
        assert result.exhausted is True

    def test_empty_response(self):
        """Should handle empty response dict."""
        service = RepromptService(validation_name="test_validator", max_attempts=2)

        llm_operation = Mock(return_value=({}, True))

        result = service.execute(
            llm_operation=llm_operation,
            original_prompt="Test prompt",
            context="test_action",
            on_exhausted="return_last",
        )

        # Empty response is invalid (valid=False)
        assert result.response == {}
        assert result.passed is False

    def test_context_string_used_in_logging(self):
        """Context string should be used for logging (smoke test)."""
        service = RepromptService(validation_name="test_validator", max_attempts=1)

        llm_operation = Mock(return_value=({"valid": True}, True))

        # Should not crash with various context strings
        result = service.execute(
            llm_operation=llm_operation,
            original_prompt="Test prompt",
            context="action=classify_book,record=123",
        )

        assert result.passed is True


class TestParameterValidation:
    """Tests for parameter validation in RepromptService and config factory."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be valid")
        def test_validator(response: dict) -> bool:
            return response.get("valid", False)

    def test_empty_validation_name_raises(self):
        """Should raise ValueError for empty validation_name."""
        with pytest.raises(ValueError, match="validation_name cannot be empty"):
            RepromptService(validation_name="", max_attempts=2)

    def test_whitespace_validation_name_raises(self):
        """Should raise ValueError for whitespace-only validation_name."""
        with pytest.raises(ValueError, match="validation_name cannot be empty"):
            RepromptService(validation_name="   ", max_attempts=2)

    def test_max_attempts_zero_raises(self):
        """Should raise ValueError for max_attempts < 1."""
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            RepromptService(validation_name="test_validator", max_attempts=0)

    def test_max_attempts_negative_raises(self):
        """Should raise ValueError for negative max_attempts."""
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            RepromptService(validation_name="test_validator", max_attempts=-1)

    def test_invalid_on_exhausted_raises(self):
        """Should raise ValueError for invalid on_exhausted value."""
        with pytest.raises(ValueError, match="on_exhausted must be one of"):
            RepromptService(validation_name="test_validator", on_exhausted="invalid")

    def test_typo_in_on_exhausted_raises(self):
        """Should catch typos in on_exhausted (e.g., 'rais' instead of 'raise')."""
        with pytest.raises(ValueError, match="on_exhausted must be one of"):
            RepromptService(validation_name="test_validator", on_exhausted="rais")

    def test_missing_validation_key_raises(self):
        """Should raise ValueError when 'validation' key is missing from config."""
        config = {"max_attempts": 3}  # Missing "validation" key

        with pytest.raises(ValueError, match="missing required 'validation' field"):
            create_reprompt_service_from_config(config)

    def test_valid_on_exhausted_values_accepted(self):
        """Should accept valid on_exhausted values."""
        # "return_last" should work
        service1 = RepromptService(validation_name="test_validator", on_exhausted="return_last")
        assert service1.on_exhausted == "return_last"

        # "raise" should work
        service2 = RepromptService(validation_name="test_validator", on_exhausted="raise")
        assert service2.on_exhausted == "raise"

    def test_max_attempts_one_is_valid(self):
        """Should accept max_attempts=1 (no retry)."""
        service = RepromptService(validation_name="test_validator", max_attempts=1)
        assert service.max_attempts == 1
