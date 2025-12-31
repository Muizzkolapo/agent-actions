"""Tests for the pre-flight validation orchestrator."""

import pytest

from agent_actions.validation.preflight import (
    PreFlightValidator,
    PreFlightValidationResult,
    validate_preflight,
)
from agent_actions.errors.preflight import PreFlightValidationError


class TestPreFlightValidator:
    """Tests for PreFlightValidator class."""

    def test_validate_passes_with_valid_template_and_context(self):
        """Test validation passes when all template variables exist in context."""
        validator = PreFlightValidator()
        result = validator.validate(
            template="{{ name }} is {{ age }} years old",
            context={"name": "Alice", "age": 30},
            agent_name="test_agent",
            mode="online",
        )

        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_fails_with_missing_template_variable(self):
        """Test validation fails when template references undefined variable."""
        validator = PreFlightValidator()
        result = validator.validate(
            template="{{ name }} lives in {{ city }}",
            context={"name": "Alice"},
            agent_name="test_agent",
            mode="online",
        )

        assert not result.is_valid
        assert len(result.errors) > 0
        assert any("city" in str(e.missing_refs) for e in result.errors)

    def test_validate_for_batch_sets_mode_correctly(self):
        """Test validate_for_batch sets mode to 'batch'."""
        validator = PreFlightValidator()
        result = validator.validate_for_batch(
            template="{{ item }}",
            context={"item": "test"},
            agent_name="batch_agent",
        )

        assert result.mode == "batch"

    def test_validate_for_online_sets_mode_correctly(self):
        """Test validate_for_online sets mode to 'online'."""
        validator = PreFlightValidator()
        result = validator.validate_for_online(
            template="{{ item }}",
            context={"item": "test"},
            agent_name="online_agent",
        )

        assert result.mode == "online"

    def test_validate_with_nested_context(self):
        """Test validation works with nested context variables."""
        validator = PreFlightValidator()
        result = validator.validate(
            template="{{ user.name }} is {{ user.age }}",
            context={"user": {"name": "Alice", "age": 30}},
            agent_name="test_agent",
            mode="online",
        )

        assert result.is_valid

    def test_validate_with_agent_config_missing_vendor(self):
        """Test validation catches missing model_vendor in agent config."""
        validator = PreFlightValidator()
        result = validator.validate(
            template="{{ content }}",
            context={"content": "test"},
            agent_name="test_agent",
            mode="online",
            agent_config={"agent_type": "generator"},  # Missing model_vendor
        )

        assert not result.is_valid
        assert any("model_vendor" in str(e.message) for e in result.errors)

    def test_validate_passes_for_tool_agent_without_vendor(self):
        """Test validation passes for tool agents without model_vendor."""
        validator = PreFlightValidator()
        result = validator.validate(
            template="{{ content }}",
            context={"content": "test"},
            agent_name="test_agent",
            mode="online",
            agent_config={"agent_type": "tool"},  # Tool type - no vendor needed
        )

        # Should not fail on missing vendor for tool agents
        vendor_errors = [e for e in result.errors if "model_vendor" in str(e.message)]
        assert len(vendor_errors) == 0


class TestPreFlightValidationResult:
    """Tests for PreFlightValidationResult class."""

    def test_format_message_with_no_issues(self):
        """Test format_message when validation passes."""
        result = PreFlightValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            mode="online",
        )
        message = result.format_message()
        assert "passed" in message.lower()

    def test_format_message_with_errors(self):
        """Test format_message includes error information."""
        from agent_actions.validation.preflight import ValidationIssue

        result = PreFlightValidationResult(
            is_valid=False,
            errors=[
                ValidationIssue(
                    message="Missing variable",
                    issue_type="error",
                    missing_refs=["field1"],
                )
            ],
            warnings=[],
            mode="online",
        )
        message = result.format_message()
        assert "error" in message.lower()
        assert "Missing variable" in message

    def test_raise_if_invalid_raises_on_errors(self):
        """Test raise_if_invalid raises PreFlightValidationError."""
        from agent_actions.validation.preflight import ValidationIssue

        result = PreFlightValidationResult(
            is_valid=False,
            errors=[
                ValidationIssue(
                    message="Test error",
                    issue_type="error",
                    missing_refs=["field1"],
                )
            ],
            warnings=[],
            mode="online",
        )

        with pytest.raises(PreFlightValidationError) as exc_info:
            result.raise_if_invalid()

        assert "Test error" in str(exc_info.value)

    def test_raise_if_invalid_does_nothing_when_valid(self):
        """Test raise_if_invalid doesn't raise when valid."""
        result = PreFlightValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            mode="online",
        )

        # Should not raise
        result.raise_if_invalid()


class TestValidatePreflightFunction:
    """Tests for the validate_preflight convenience function."""

    def test_validate_preflight_returns_result(self):
        """Test validate_preflight returns PreFlightValidationResult."""
        result = validate_preflight(
            template="{{ name }}",
            context={"name": "test"},
            raise_on_error=False,
        )

        assert isinstance(result, PreFlightValidationResult)
        assert result.is_valid

    def test_validate_preflight_raises_on_error_when_enabled(self):
        """Test validate_preflight raises when raise_on_error=True."""
        with pytest.raises(PreFlightValidationError):
            validate_preflight(
                template="{{ missing_var }}",
                context={},
                raise_on_error=True,
            )

    def test_validate_preflight_does_not_raise_when_disabled(self):
        """Test validate_preflight doesn't raise when raise_on_error=False."""
        result = validate_preflight(
            template="{{ missing_var }}",
            context={},
            raise_on_error=False,
        )

        assert not result.is_valid


class TestBatchOnlineConsistency:
    """Tests to verify batch and online modes produce consistent errors."""

    def test_same_error_for_missing_variable(self):
        """Test batch and online produce same error for missing variable."""
        validator = PreFlightValidator()

        batch_result = validator.validate_for_batch(
            template="{{ missing_field }}",
            context={"other_field": "value"},
            agent_name="test_agent",
        )

        # Reset validator
        validator = PreFlightValidator()

        online_result = validator.validate_for_online(
            template="{{ missing_field }}",
            context={"other_field": "value"},
            agent_name="test_agent",
        )

        # Both should fail
        assert not batch_result.is_valid
        assert not online_result.is_valid

        # Both should have same error message structure
        assert len(batch_result.errors) == len(online_result.errors)
        for batch_err, online_err in zip(batch_result.errors, online_result.errors):
            assert batch_err.message == online_err.message
            assert batch_err.missing_refs == online_err.missing_refs

    def test_error_format_is_consistent(self):
        """Test error format message is consistent between modes."""
        validator = PreFlightValidator()

        batch_result = validator.validate_for_batch(
            template="{{ x }}",
            context={},
            agent_name="agent",
        )

        validator = PreFlightValidator()

        online_result = validator.validate_for_online(
            template="{{ x }}",
            context={},
            agent_name="agent",
        )

        batch_msg = batch_result.format_message()
        online_msg = online_result.format_message()

        # Messages should be structurally similar (differ only in mode)
        assert "error" in batch_msg.lower() or "ERROR" in batch_msg
        assert "error" in online_msg.lower() or "ERROR" in online_msg
