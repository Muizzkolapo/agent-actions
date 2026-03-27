"""Tests that Pydantic field validators raise ValueError (not ConfigValidationError)
so Pydantic can properly collect them into ValidationError."""

import pytest
from pydantic import ValidationError

from agent_actions.config.environment import EnvironmentConfig
from agent_actions.config.schema import ActionConfig


class TestEnvironmentValidators:
    def test_short_api_key_raises_validation_error(self):
        """API key <10 chars should be caught by Pydantic as ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            EnvironmentConfig(openai_api_key="short")
        assert "API key must be at least 10 characters" in str(exc_info.value)

    def test_bad_database_url_raises_validation_error(self):
        """Invalid DB URL prefix should be caught by Pydantic as ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            EnvironmentConfig(database_url="redis://localhost")
        assert "Database URL must start with" in str(exc_info.value)


class TestSchemaValidators:
    def test_invalid_guard_type_raises_validation_error(self):
        """Guard with invalid type should produce a Pydantic ValidationError."""
        with pytest.raises(ValidationError):
            ActionConfig(name="test", intent="test", guard=123)

    def test_valid_guard_string_passes(self):
        """Valid guard string should not raise."""
        action = ActionConfig(name="test", intent="test", guard="field == 'value'")
        assert action.guard == "field == 'value'"
