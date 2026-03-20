"""Regression tests for A-1: api_key must not appear in repr/logs."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from agent_actions.config.schema import ActionConfig, DefaultsConfig


class TestActionConfigApiKeySecret:
    def _minimal(self, **kwargs) -> dict:
        return {
            "name": "test_action",
            "intent": "test intent",
            **kwargs,
        }

    def test_repr_does_not_expose_raw_key(self):
        config = ActionConfig(**self._minimal(api_key="secret123"))
        assert "secret123" not in repr(config)
        assert "**********" in repr(config)  # masking sentinel must be present

    def test_model_dump_does_not_expose_raw_key(self):
        config = ActionConfig(**self._minimal(api_key="secret123"))
        assert "secret123" not in str(config.model_dump())
        assert "**********" in str(config.model_dump())
        assert "secret123" not in str(config.model_dump(mode="json"))
        assert "**********" in str(config.model_dump(mode="json"))

    def test_get_secret_value_returns_raw_key(self):
        config = ActionConfig(**self._minimal(api_key="secret123"))
        assert config.api_key.get_secret_value() == "secret123"

    def test_none_api_key_is_none(self):
        config = ActionConfig(**self._minimal())
        assert config.api_key is None


class TestDefaultsConfigApiKeySecret:
    def test_repr_does_not_expose_raw_key(self):
        config = DefaultsConfig(api_key="defaults_secret")
        assert "defaults_secret" not in repr(config)
        assert "**********" in repr(config)

    def test_model_dump_does_not_expose_raw_key(self):
        config = DefaultsConfig(api_key="defaults_secret")
        assert "defaults_secret" not in str(config.model_dump())
        assert "**********" in str(config.model_dump())
        assert "defaults_secret" not in str(config.model_dump(mode="json"))
        assert "**********" in str(config.model_dump(mode="json"))

    def test_get_secret_value_returns_raw_key(self):
        config = DefaultsConfig(api_key="defaults_secret")
        assert config.api_key.get_secret_value() == "defaults_secret"


class TestBatchClientFactorySecretStr:
    """Verify that the actual factory functions unwrap SecretStr before passing to clients."""

    def test_openai_factory_unwraps_secret_str(self):
        from agent_actions.llm.providers.batch_client_factory import _create_openai

        with patch(
            "agent_actions.llm.providers.openai.batch_client.OpenAIBatchClient"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_openai({"api_key": SecretStr("sk-openai-test")})

        mock_cls.assert_called_once_with(api_key="sk-openai-test")

    def test_openai_factory_passes_plain_str_unchanged(self):
        from agent_actions.llm.providers.batch_client_factory import _create_openai

        with patch(
            "agent_actions.llm.providers.openai.batch_client.OpenAIBatchClient"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_openai({"api_key": "sk-plain"})

        mock_cls.assert_called_once_with(api_key="sk-plain")

    @pytest.mark.parametrize("factory_name", [
        "_create_gemini",
        "_create_anthropic",
        "_create_groq",
        "_create_mistral",
    ])
    def test_optional_vendor_factories_unwrap_secret_str(self, factory_name):
        """All vendor factories must unwrap SecretStr before passing api_key to the client."""
        import agent_actions.llm.providers.batch_client_factory as factory_module

        factory_fn = getattr(factory_module, factory_name)
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()

        with patch.object(factory_module, "_try_import", return_value=(mock_cls, True)):
            factory_fn({"api_key": SecretStr("sk-vendor-test")})

        mock_cls.assert_called_once()
        assert mock_cls.call_args.kwargs["api_key"] == "sk-vendor-test"

    def test_cache_key_unwraps_secret_str(self):
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        key_with_secret = BatchClientResolver._build_cache_key(
            "openai", {"api_key": SecretStr("sk-abc123")}
        )
        key_with_plain = BatchClientResolver._build_cache_key(
            "openai", {"api_key": "sk-abc123"}
        )
        # Both should produce the same cache key (same underlying string)
        assert key_with_secret == key_with_plain
        assert key_with_secret.startswith("openai:")

    def test_cache_key_vendor_specific_fallback_unwraps_secret_str(self):
        """The f'{client_type}_api_key' fallback in _build_cache_key also handles SecretStr."""
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        key_with_secret = BatchClientResolver._build_cache_key(
            "openai", {"openai_api_key": SecretStr("sk-vendor-fallback")}
        )
        key_with_plain = BatchClientResolver._build_cache_key(
            "openai", {"openai_api_key": "sk-vendor-fallback"}
        )
        assert key_with_secret == key_with_plain
        assert key_with_secret.startswith("openai:")
