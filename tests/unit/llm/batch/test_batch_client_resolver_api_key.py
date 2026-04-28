"""Tests for batch client resolver API key resolution.

Verifies that batch mode resolves the generic ``api_key`` field from agent
config using the same ``BaseClient.get_api_key()`` path that online mode uses,
eliminating the dual-path divergence where batch mode only checked
vendor-specific fields (``gemini_api_key``, ``openai_api_key``).
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)


def _make_agent_config(
    vendor: str,
    api_key_env_name: str = "MY_CUSTOM_KEY",
) -> dict:
    """Build a minimal agent config with the generic api_key field."""
    return {
        "agent_type": "test_action",
        "model_vendor": vendor,
        "model_name": "test-model",
        "api_key": api_key_env_name,
    }


def _extract_client_config(mock_create: MagicMock) -> dict:
    """Extract the config dict passed to BatchClientFactory.create_client."""
    args, kwargs = mock_create.call_args
    if len(args) > 1:
        return args[1]
    return kwargs.get("config", {})


@pytest.fixture()
def resolver():
    return BatchClientResolver()


_PATCH_TARGET = (
    "agent_actions.llm.batch.infrastructure.batch_client_resolver.BatchClientFactory.create_client"
)


class TestBatchApiKeyResolution:
    """Batch mode resolves api_key from agent config for all vendors."""

    @pytest.mark.parametrize(
        "vendor",
        ["openai", "gemini", "anthropic", "groq", "mistral"],
    )
    def test_generic_api_key_resolved_for_all_vendors(
        self,
        vendor,
        resolver,
        monkeypatch,
    ):
        """api_key env var in config is resolved and passed to factory."""
        monkeypatch.setenv("MY_CUSTOM_KEY", "sk-resolved-secret")

        mock_client = MagicMock()
        mock_client.validate_config.return_value = (True, None)

        with patch(_PATCH_TARGET, return_value=mock_client) as mock_create:
            config = _make_agent_config(vendor)
            resolver.get_for_config(config)

            mock_create.assert_called_once()
            client_config = _extract_client_config(mock_create)
            assert client_config["api_key"] == "sk-resolved-secret"

    def test_env_var_interpolation_syntax(
        self,
        resolver,
        monkeypatch,
    ):
        """api_key using ${VAR} syntax is resolved correctly."""
        monkeypatch.setenv("INTERP_KEY", "sk-interpolated")

        mock_client = MagicMock()
        mock_client.validate_config.return_value = (True, None)

        with patch(_PATCH_TARGET, return_value=mock_client) as mock_create:
            config = _make_agent_config(
                "openai",
                api_key_env_name="${INTERP_KEY}",
            )
            resolver.get_for_config(config)

            client_config = _extract_client_config(mock_create)
            assert client_config["api_key"] == "sk-interpolated"

    def test_missing_env_var_raises_configuration_error(
        self,
        resolver,
        monkeypatch,
    ):
        """Missing env var named in api_key raises ConfigurationError."""
        monkeypatch.delenv("NONEXISTENT_KEY", raising=False)

        config = _make_agent_config(
            "openai",
            api_key_env_name="NONEXISTENT_KEY",
        )
        with pytest.raises(ConfigurationError, match="not set"):
            resolver.get_for_config(config)

    def test_no_api_key_in_config_passes_empty_config(
        self,
        resolver,
        monkeypatch,
    ):
        """No api_key in config -> factory gets empty config dict."""
        mock_client = MagicMock()
        mock_client.validate_config.return_value = (True, None)

        with patch(_PATCH_TARGET, return_value=mock_client) as mock_create:
            config = {
                "agent_type": "test_action",
                "model_vendor": "openai",
                "model_name": "test-model",
            }
            resolver.get_for_config(config)

            client_config = _extract_client_config(mock_create)
            assert client_config == {}

    def test_empty_api_key_string_passes_empty_config(
        self,
        resolver,
        monkeypatch,
    ):
        """Empty string api_key -> factory gets empty config dict."""
        mock_client = MagicMock()
        mock_client.validate_config.return_value = (True, None)

        with patch(_PATCH_TARGET, return_value=mock_client) as mock_create:
            config = _make_agent_config("openai", api_key_env_name="")
            config["api_key"] = ""
            resolver.get_for_config(config)

            client_config = _extract_client_config(mock_create)
            assert client_config == {}


class TestBatchCacheKeyUsesGenericApiKey:
    """_build_cache_key uses generic api_key, not vendor-specific."""

    def test_cache_key_includes_api_key_hash(self):
        config = {"api_key": "MY_SECRET_VAR"}
        key = BatchClientResolver._build_cache_key("openai", config)
        assert key.startswith("openai:")
        assert len(key) > len("openai:")

    def test_different_api_keys_produce_different_cache_keys(self):
        key_a = BatchClientResolver._build_cache_key(
            "openai",
            {"api_key": "KEY_A"},
        )
        key_b = BatchClientResolver._build_cache_key(
            "openai",
            {"api_key": "KEY_B"},
        )
        assert key_a != key_b

    def test_no_api_key_returns_vendor_only(self):
        key = BatchClientResolver._build_cache_key("openai", {})
        assert key == "openai"

    def test_vendor_specific_key_ignored(self):
        """Vendor-specific fields like openai_api_key are not used."""
        config = {"openai_api_key": "SOME_KEY"}
        key = BatchClientResolver._build_cache_key("openai", config)
        assert key == "openai"
