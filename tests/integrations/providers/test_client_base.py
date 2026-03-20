"""Tests for BaseClient API key validation."""

import pytest
from pydantic import SecretStr

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.client_base import BaseClient


class TestClientBaseAPIKeyValidation:
    """Test API key environment variable validation."""

    def test_api_key_env_var_not_set(self, monkeypatch):
        """Test error when referenced env var doesn't exist."""
        monkeypatch.delenv("NONEXISTENT_TEST_KEY_12345", raising=False)
        agent_config = {"agent_type": "test_agent", "api_key": "${NONEXISTENT_TEST_KEY_12345}"}
        with pytest.raises(ConfigurationError) as exc_info:
            BaseClient.get_api_key(agent_config)
        error = exc_info.value
        error_str = str(error)
        assert "NONEXISTENT_TEST_KEY_12345" in error_str
        assert "is not set" in error_str
        assert error.context["env_var"] == "NONEXISTENT_TEST_KEY_12345"
        assert error.context["config_value"] == "${NONEXISTENT_TEST_KEY_12345}"
        assert "export" in error.context["hint"]

    def test_api_key_env_var_empty(self, monkeypatch):
        """Test error when env var is set but empty."""
        monkeypatch.setenv("TEST_EMPTY_KEY_12345", "")
        agent_config = {"agent_type": "test_agent", "api_key": "${TEST_EMPTY_KEY_12345}"}
        with pytest.raises(ConfigurationError) as exc_info:
            BaseClient.get_api_key(agent_config)
        error = exc_info.value
        error_str = str(error)
        assert "TEST_EMPTY_KEY_12345" in error_str
        assert "empty" in error_str.lower()
        assert error.context["env_var"] == "TEST_EMPTY_KEY_12345"
        assert "export" in error.context["hint"]

    def test_api_key_env_var_success(self, monkeypatch):
        """Test successful env var resolution with ${} syntax."""
        monkeypatch.setenv("TEST_SUCCESS_KEY_12345", "test-api-key-value")
        agent_config = {"agent_type": "test_agent", "api_key": "${TEST_SUCCESS_KEY_12345}"}
        result = BaseClient.get_api_key(agent_config)
        assert result == "test-api-key-value"

    def test_api_key_legacy_format_success(self, monkeypatch):
        """Test successful env var resolution with legacy format (no ${})."""
        monkeypatch.setenv("TEST_LEGACY_KEY_12345", "legacy-api-key-value")
        agent_config = {"agent_type": "test_agent", "api_key": "TEST_LEGACY_KEY_12345"}
        result = BaseClient.get_api_key(agent_config)
        assert result == "legacy-api-key-value"

    def test_api_key_secret_str_is_unwrapped(self, monkeypatch):
        """SecretStr api_key is unwrapped before startswith() — no AttributeError."""
        monkeypatch.setenv("TEST_SECRET_STR_KEY_12345", "secret-api-key-value")
        agent_config = {
            "agent_type": "test_agent",
            "api_key": SecretStr("TEST_SECRET_STR_KEY_12345"),
        }
        result = BaseClient.get_api_key(agent_config)
        assert result == "secret-api-key-value"

    def test_api_key_missing_from_config(self):
        """Test error when api_key field is missing from config."""
        agent_config = {"agent_type": "test_agent"}
        with pytest.raises(ConfigurationError) as exc_info:
            BaseClient.get_api_key(agent_config)
        error = exc_info.value
        error_str = str(error)
        assert "missing" in error_str.lower()
        assert "hint" in error.context
        assert "agent_actions.yml" in error.context["hint"] or "workflow" in error.context["hint"]
