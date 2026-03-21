"""Regression tests for #1159: v1 api_key must not appear in repr/logs."""

from agent_actions.output.response.config_schema import AgentConfig, DefaultAgentConfig


class TestDefaultAgentConfigApiKeySecret:
    def test_repr_does_not_expose_raw_key(self):
        config = DefaultAgentConfig(api_key="secret123")
        assert "secret123" not in repr(config)
        assert "**********" in repr(config)

    def test_model_dump_does_not_expose_raw_key(self):
        config = DefaultAgentConfig(api_key="secret123")
        assert "secret123" not in str(config.model_dump())
        assert "**********" in str(config.model_dump())
        assert "secret123" not in str(config.model_dump(mode="json"))
        assert "**********" in str(config.model_dump(mode="json"))

    def test_get_secret_value_returns_raw_key(self):
        config = DefaultAgentConfig(api_key="secret123")
        assert config.api_key.get_secret_value() == "secret123"

    def test_none_api_key_is_none(self):
        config = DefaultAgentConfig()
        assert config.api_key is None


class TestAgentConfigApiKeySecret:
    def _minimal(self, **kwargs) -> dict:
        return {"agent_type": "test_agent", **kwargs}

    def test_repr_does_not_expose_raw_key(self):
        config = AgentConfig(**self._minimal(api_key="secret456"))
        assert "secret456" not in repr(config)
        assert "**********" in repr(config)

    def test_model_dump_does_not_expose_raw_key(self):
        config = AgentConfig(**self._minimal(api_key="secret456"))
        assert "secret456" not in str(config.model_dump())
        assert "**********" in str(config.model_dump())
        assert "secret456" not in str(config.model_dump(mode="json"))
        assert "**********" in str(config.model_dump(mode="json"))

    def test_get_secret_value_returns_raw_key(self):
        config = AgentConfig(**self._minimal(api_key="secret456"))
        assert config.api_key.get_secret_value() == "secret456"

    def test_none_api_key_is_none(self):
        config = AgentConfig(**self._minimal())
        assert config.api_key is None
