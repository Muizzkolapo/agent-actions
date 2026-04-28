"""Regression tests for A-1: api_key must not appear in repr/logs."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from agent_actions.config.schema import ActionConfig, DefaultsConfig
from agent_actions.output.response.config_schema import AgentConfig, DefaultAgentConfig


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

        with patch("agent_actions.llm.providers.openai.batch_client.OpenAIBatchClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_openai({"api_key": SecretStr("sk-openai-test")})

        mock_cls.assert_called_once_with(api_key="sk-openai-test")

    def test_openai_factory_passes_plain_str_unchanged(self):
        from agent_actions.llm.providers.batch_client_factory import _create_openai

        with patch("agent_actions.llm.providers.openai.batch_client.OpenAIBatchClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_openai({"api_key": "sk-plain"})

        mock_cls.assert_called_once_with(api_key="sk-plain")

    @pytest.mark.parametrize(
        "factory_name",
        [
            "_create_gemini",
            "_create_anthropic",
            "_create_groq",
            "_create_mistral",
        ],
    )
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
        key_with_plain = BatchClientResolver._build_cache_key("openai", {"api_key": "sk-abc123"})
        # Both should produce the same cache key (same underlying string)
        assert key_with_secret == key_with_plain
        assert key_with_secret.startswith("openai:")

    def test_cache_key_unwraps_secret_str(self):
        """_build_cache_key handles SecretStr in the generic api_key field."""
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        key_with_secret = BatchClientResolver._build_cache_key(
            "openai", {"api_key": SecretStr("sk-vendor-fallback")}
        )
        key_with_plain = BatchClientResolver._build_cache_key(
            "openai", {"api_key": "sk-vendor-fallback"}
        )
        assert key_with_secret == key_with_plain
        assert key_with_secret.startswith("openai:")


class TestAgentConfigApiKeySecret:
    """Verify AgentConfig.api_key uses SecretStr (runtime pipeline gap fix, #1160)."""

    def test_repr_does_not_expose_raw_key(self):
        config = AgentConfig(agent_type="test", api_key="secret123")
        assert "secret123" not in repr(config)
        assert "**********" in repr(config)

    def test_model_dump_python_preserves_secret_str(self):
        config = AgentConfig(agent_type="test", api_key="secret123")
        dumped = config.model_dump()
        assert isinstance(dumped["api_key"], SecretStr)

    def test_model_dump_json_returns_masked_string(self):
        config = AgentConfig(agent_type="test", api_key="secret123")
        dumped = config.model_dump(mode="json")
        assert dumped["api_key"] == "**********"
        assert "secret123" not in str(dumped)

    def test_get_secret_value_returns_raw_key(self):
        config = AgentConfig(agent_type="test", api_key="secret123")
        assert config.api_key.get_secret_value() == "secret123"

    def test_none_api_key_is_none(self):
        config = AgentConfig(agent_type="test")
        assert config.api_key is None

    def test_plain_string_coerced_to_secret_str(self):
        config = AgentConfig.model_validate({"agent_type": "test", "api_key": "plain"})
        assert isinstance(config.api_key, SecretStr)
        assert config.api_key.get_secret_value() == "plain"


class TestDefaultAgentConfigApiKeySecret:
    """Verify DefaultAgentConfig.api_key uses SecretStr (#1160)."""

    def test_repr_does_not_expose_raw_key(self):
        config = DefaultAgentConfig(api_key="defaults_secret")
        assert "defaults_secret" not in repr(config)
        assert "**********" in repr(config)

    def test_model_dump_python_preserves_secret_str(self):
        config = DefaultAgentConfig(api_key="defaults_secret")
        dumped = config.model_dump()
        assert isinstance(dumped["api_key"], SecretStr)

    def test_model_dump_json_returns_masked_string(self):
        config = DefaultAgentConfig(api_key="defaults_secret")
        dumped = config.model_dump(mode="json")
        assert dumped["api_key"] == "**********"

    def test_get_secret_value_returns_raw_key(self):
        config = DefaultAgentConfig(api_key="defaults_secret")
        assert config.api_key.get_secret_value() == "defaults_secret"


class TestEndToEndSecretStrPipeline:
    """Integration: verify SecretStr flows end-to-end through the config pipeline (#1160)."""

    def test_expander_output_coerced_to_secret_str_by_agent_config(self):
        """After expander produces a plain-str api_key dict,
        AgentConfig.model_validate() must coerce it to SecretStr."""
        from agent_actions.output.response.expander import ActionExpander

        workflow = {
            "name": "test_wf",
            "actions": [
                {
                    "name": "classify",
                    "intent": "Classify items",
                    "model_vendor": "openai",
                    "model_name": "gpt-4",
                    "api_key": "sk-secret-e2e",
                }
            ],
            "defaults": {},
        }
        result = ActionExpander.expand_actions_to_agents(workflow)
        agents = result["test_wf"]
        assert len(agents) == 1

        # The expander returns a raw dict with plain str api_key
        assert agents[0]["api_key"] == "sk-secret-e2e"
        assert isinstance(agents[0]["api_key"], str)

        # AgentConfig.model_validate() must coerce to SecretStr
        config = AgentConfig.model_validate(agents[0])
        assert isinstance(config.api_key, SecretStr)
        assert config.api_key.get_secret_value() == "sk-secret-e2e"

        # model_dump() must preserve SecretStr
        dumped = config.model_dump()
        assert isinstance(dumped["api_key"], SecretStr)

    def test_model_dump_roundtrip_preserves_secret_str(self):
        """model_dump() -> model_validate() round-trip must preserve SecretStr."""
        original = AgentConfig(agent_type="test", api_key="sk-roundtrip")
        dumped = original.model_dump()
        restored = AgentConfig.model_validate(dumped)
        assert isinstance(restored.api_key, SecretStr)
        assert restored.api_key.get_secret_value() == "sk-roundtrip"

    def test_manager_serialization_path_preserves_secret_str(self):
        """When manager.py serializes a validated ActionConfig via model_dump(mode='python'),
        api_key must remain SecretStr through the expander to the final agent dict.
        This verifies the fix for the validate-and-discard pattern (issue #1174)."""
        from agent_actions.output.response.expander import ActionExpander

        action_model = ActionConfig(
            name="classify",
            intent="Classify items",
            model_vendor="openai",
            model_name="gpt-4",
            api_key="sk-manager-path",
        )
        # Simulate what manager.py now does after capturing the validated WorkflowConfig
        action_dict = action_model.model_dump(mode="python", exclude_unset=True, by_alias=True)
        assert isinstance(action_dict["api_key"], SecretStr)

        # Unlike test_expander_output_coerced_to_secret_str_by_agent_config (which feeds
        # plain-str dicts and expects plain-str output), here the input dict already
        # contains a SecretStr — the expander passes it through opaquely.
        # When expander receives a Pydantic-serialized dict, SecretStr flows through
        result = ActionExpander.expand_actions_to_agents(
            {"name": "test_wf", "actions": [action_dict], "defaults": {}}
        )
        agent = result["test_wf"][0]
        assert isinstance(agent["api_key"], SecretStr)
        assert agent["api_key"].get_secret_value() == "sk-manager-path"

    def test_defaults_dump_flows_into_agent_config_as_secret_str(self):
        """DefaultAgentConfig.model_dump() -> merge -> AgentConfig.model_validate()
        must preserve SecretStr through the merge path."""
        default_model = DefaultAgentConfig(api_key="sk-default-key")
        default_dict = default_model.model_dump()

        # Simulate the merge path from manager.py:merge_agent_configs
        # (manager also supplies chunk_config default; we only test api_key flow)
        agent_dict = {"agent_type": "test", "chunk_config": {}}
        merged = {**default_dict, **agent_dict}

        config = AgentConfig.model_validate(merged)
        assert isinstance(config.api_key, SecretStr)
        assert config.api_key.get_secret_value() == "sk-default-key"
