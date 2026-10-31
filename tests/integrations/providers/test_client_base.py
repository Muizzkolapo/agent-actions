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

    @pytest.mark.parametrize(
        ("api_key", "env", "value"),
        [
            ("${TEST_SUCCESS_KEY_12345}", "TEST_SUCCESS_KEY_12345", "test-api-key-value"),
            ("TEST_LEGACY_KEY_12345", "TEST_LEGACY_KEY_12345", "legacy-api-key-value"),
            (
                SecretStr("TEST_SECRET_STR_KEY_12345"),
                "TEST_SECRET_STR_KEY_12345",
                "secret-api-key-value",
            ),
        ],
        ids=["dollar-brace", "bare-name", "secretstr-unwrapped"],
    )
    def test_api_key_resolves_from_env_var(self, monkeypatch, api_key, env, value):
        """`${NAME}`, a bare NAME and a SecretStr wrapping NAME all read the variable."""
        monkeypatch.setenv(env, value)
        agent_config = {"agent_type": "test_agent", "api_key": api_key}
        assert BaseClient.get_api_key(agent_config) == value

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
