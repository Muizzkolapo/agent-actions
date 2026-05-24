"""Behavioral tests for the Ollama local vs cloud vendor split.

Verifies the concrete behavioral differences between OllamaLocalClient and
OllamaCloudClient, plus OllamaBatchClient construction and invocation
differences when ``cloud=True`` vs ``cloud=False``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.defaults import OllamaCloudDefaults
from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.ollama.client import (
    OllamaCloudClient,
    OllamaLocalClient,
    _build_ollama_client,
    _call_ollama_json,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PROMPT = "Classify the item."
CONTEXT = "A red apple"
SCHEMA = {
    "name": "classification",
    "schema": {"type": "object", "properties": {"label": {"type": "string"}}},
}


def _make_agent_config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "model_name": "llama3",
        "agent_type": "test_action",
    }
    config.update(overrides)
    return config


def _fake_chat_response(content: str = '{"label": "fruit"}') -> SimpleNamespace:
    """Return a minimal object that looks like an Ollama chat response."""
    return SimpleNamespace(
        message=SimpleNamespace(role="assistant", content=content),
        done=True,
        prompt_eval_count=10,
        eval_count=5,
    )


# ---------------------------------------------------------------------------
# OllamaLocalClient
# ---------------------------------------------------------------------------


class TestOllamaLocalClient:
    """Local client: no auth, API-enforced structured output via format param."""

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_invoke_does_not_call_get_api_key(self, mock_mb, mock_build, mock_fire, mock_rb):
        """OllamaLocalClient.invoke bypasses get_api_key entirely."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response()
        mock_build.return_value = mock_client

        config = _make_agent_config()

        # If get_api_key were called, it would raise ConfigurationError
        # because there is no api_key in the config. The fact that this
        # succeeds proves get_api_key is never called.
        result = OllamaLocalClient.invoke(config, PROMPT, CONTEXT, SCHEMA)
        assert isinstance(result, list)
        assert result[0]["label"] == "fruit"

    def test_client_construction_no_auth_header(self):
        """_build_ollama_client(cloud=False) creates Client without auth headers."""
        config = _make_agent_config()
        with patch("agent_actions.llm.providers.ollama.client.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            _build_ollama_client(config, api_key=None, cloud=False)

            call_kwargs = mock_cls.call_args
            # Should NOT have a headers kwarg with Authorization
            if call_kwargs.kwargs:
                assert "headers" not in call_kwargs.kwargs
            if call_kwargs.args:
                # Client() or Client(host=...) — no headers positional arg
                pass

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_call_json_passes_format_param(self, mock_mb, mock_build, mock_fire, mock_rb):
        """Local JSON call passes the ``format`` kwarg to client.chat()."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response()
        mock_build.return_value = mock_client

        config = _make_agent_config()
        _call_ollama_json(
            None,
            config,
            PROMPT,
            CONTEXT,
            SCHEMA,
            vendor_slug="ollama_local",
            cloud=False,
        )

        chat_kwargs = mock_client.chat.call_args.kwargs
        assert "format" in chat_kwargs, "Local JSON call must pass 'format' to chat()"
        # With a schema, format should be the extracted schema dict
        assert isinstance(chat_kwargs["format"], dict)

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_call_json_passes_format_json_string_when_no_schema(
        self, mock_mb, mock_build, mock_fire, mock_rb
    ):
        """Without a schema, local JSON call passes format='json'."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response()
        mock_build.return_value = mock_client

        config = _make_agent_config()
        _call_ollama_json(
            None,
            config,
            PROMPT,
            CONTEXT,
            None,
            vendor_slug="ollama_local",
            cloud=False,
        )

        chat_kwargs = mock_client.chat.call_args.kwargs
        assert chat_kwargs["format"] == "json"

    def test_base_url_from_config(self):
        """base_url in agent_config overrides default host."""
        config = _make_agent_config(base_url="http://my-ollama:11434")
        with patch("agent_actions.llm.providers.ollama.client.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            _build_ollama_client(config, api_key=None, cloud=False)

            call_kwargs = mock_cls.call_args
            assert call_kwargs.kwargs.get("host") == "http://my-ollama:11434"

    @patch.dict("os.environ", {"OLLAMA_HOST": "http://env-ollama:11434"})
    def test_base_url_from_env(self):
        """OLLAMA_HOST env var is used when base_url is not in config."""
        config = _make_agent_config()
        with patch("agent_actions.llm.providers.ollama.client.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            _build_ollama_client(config, api_key=None, cloud=False)

            call_kwargs = mock_cls.call_args
            assert call_kwargs.kwargs.get("host") == "http://env-ollama:11434"

    def test_base_url_defaults_to_no_host_kwarg(self):
        """With no base_url in config and no OLLAMA_HOST env, Client() is called bare."""
        config = _make_agent_config()
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("agent_actions.llm.providers.ollama.client.Client") as mock_cls,
        ):
            # Remove OLLAMA_HOST if it exists
            import os

            env_backup = os.environ.pop("OLLAMA_HOST", None)
            try:
                mock_cls.return_value = MagicMock()
                _build_ollama_client(config, api_key=None, cloud=False)
                # Called with no arguments
                mock_cls.assert_called_once_with()
            finally:
                if env_backup is not None:
                    os.environ["OLLAMA_HOST"] = env_backup


# ---------------------------------------------------------------------------
# OllamaCloudClient
# ---------------------------------------------------------------------------


class TestOllamaCloudClient:
    """Cloud client: Bearer auth, schema injected via prompt (not format param)."""

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_invoke_calls_get_api_key(self, mock_mb, mock_build, mock_fire, mock_rb):
        """OllamaCloudClient.invoke (inherited from BaseClient) calls get_api_key.

        Without a valid api_key config, invoking the cloud client raises
        ConfigurationError, proving get_api_key is in the call path.
        """
        config = _make_agent_config()
        # No api_key in config => get_api_key raises ConfigurationError
        with pytest.raises(ConfigurationError, match="API key configuration is missing"):
            OllamaCloudClient.invoke(config, PROMPT, CONTEXT, SCHEMA)

    def test_client_construction_has_bearer_header(self):
        """_build_ollama_client(cloud=True) passes Authorization: Bearer header."""
        config = _make_agent_config()
        with patch("agent_actions.llm.providers.ollama.client.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            _build_ollama_client(config, api_key="test-key-123", cloud=True)

            call_kwargs = mock_cls.call_args.kwargs
            assert "headers" in call_kwargs
            assert call_kwargs["headers"]["Authorization"] == "Bearer test-key-123"

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_call_json_omits_format_param(self, mock_mb, mock_build, mock_fire, mock_rb):
        """Cloud JSON call does NOT pass the ``format`` kwarg to chat()."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response()
        mock_build.return_value = mock_client

        config = _make_agent_config()
        _call_ollama_json(
            "some-api-key",
            config,
            PROMPT,
            CONTEXT,
            SCHEMA,
            vendor_slug="ollama_cloud",
            cloud=True,
        )

        chat_kwargs = mock_client.chat.call_args.kwargs
        assert "format" not in chat_kwargs, (
            "Cloud JSON call must NOT pass 'format' to chat() (structured output not supported yet)"
        )

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_call_json_returns_error_dict_on_invalid_json(
        self, mock_mb, mock_build, mock_fire, mock_rb
    ):
        """Invalid JSON returns error dict instead of raising VendorAPIError."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response(content="not json at all")
        mock_build.return_value = mock_client

        config = _make_agent_config()
        result = _call_ollama_json(
            "some-api-key",
            config,
            PROMPT,
            CONTEXT,
            SCHEMA,
            vendor_slug="ollama_cloud",
            cloud=True,
        )

        assert len(result) == 1
        assert result[0]["_parse_error"]
        assert result[0]["raw_response"] == "not json at all"

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_cloud_repair_recovers_fenced_json(self, mock_mb, mock_build, mock_fire, mock_rb):
        """Cloud path recovers valid JSON wrapped in markdown fences."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        fenced = '```json\n{"label": "fruit"}\n```'
        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response(content=fenced)
        mock_build.return_value = mock_client

        config = _make_agent_config()
        result = _call_ollama_json(
            "key",
            config,
            PROMPT,
            CONTEXT,
            SCHEMA,
            vendor_slug="ollama_cloud",
            cloud=True,
        )

        assert len(result) == 1
        assert result[0]["label"] == "fruit"
        assert "_parse_error" not in result[0]


# ---------------------------------------------------------------------------
# Schema-echo prevention: title stripped from format param
# ---------------------------------------------------------------------------


class TestSchemaEchoPrevention:
    """Regression: _extract_ollama_schema strips ``title`` to prevent echo."""

    def test_title_stripped_from_ollama_format(self):
        """Compiled Ollama schema has title — format param must NOT."""
        from agent_actions.llm.providers.ollama.client import _extract_ollama_schema

        compiled = {
            "title": "InlineSchema",
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
        result = _extract_ollama_schema(compiled)
        assert "title" not in result
        assert result["type"] == "object"
        assert "answer" in result["properties"]

    def test_title_stripped_from_nested_schema(self):
        """OpenAI-wrapped schema with title in inner dict — title stripped."""
        from agent_actions.llm.providers.ollama.client import _extract_ollama_schema

        wrapped = {
            "name": "InlineSchema",
            "schema": {
                "title": "InlineSchema",
                "type": "object",
                "properties": {"x": {"type": "string"}},
            },
        }
        result = _extract_ollama_schema(wrapped)
        assert "title" not in result
        assert result["type"] == "object"

    def test_schema_without_title_unchanged(self):
        """Schema without title passes through unmodified."""
        from agent_actions.llm.providers.ollama.client import _extract_ollama_schema

        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": [],
        }
        result = _extract_ollama_schema(schema)
        assert result == schema

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_local_chat_format_has_no_title(self, mock_mb, mock_build, mock_fire, mock_rb):
        """End-to-end: title never reaches client.chat(format=...) for local."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response()
        mock_build.return_value = mock_client

        compiled_schema = {
            "title": "InlineSchema",
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        }
        config = _make_agent_config()
        OllamaLocalClient.invoke(config, PROMPT, CONTEXT, compiled_schema)

        chat_kwargs = mock_client.chat.call_args
        format_param = chat_kwargs.kwargs.get("format") or chat_kwargs[1].get("format")
        assert isinstance(format_param, dict)
        assert "title" not in format_param

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_cloud_repair_recovers_trailing_comma(self, mock_mb, mock_build, mock_fire, mock_rb):
        """Cloud path recovers JSON with trailing commas."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        bad_json = '{"label": "fruit",}'
        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response(content=bad_json)
        mock_build.return_value = mock_client

        config = _make_agent_config()
        result = _call_ollama_json(
            "key",
            config,
            PROMPT,
            CONTEXT,
            SCHEMA,
            vendor_slug="ollama_cloud",
            cloud=True,
        )

        assert len(result) == 1
        assert result[0]["label"] == "fruit"
        assert "_parse_error" not in result[0]

    @patch("agent_actions.llm.providers.ollama.client.ResponseBuilder")
    @patch("agent_actions.llm.providers.ollama.client.fire_event")
    @patch("agent_actions.llm.providers.ollama.client._build_ollama_client")
    @patch("agent_actions.llm.providers.ollama.client.MessageBuilder")
    def test_local_parse_failure_returns_error_dict(self, mock_mb, mock_build, mock_fire, mock_rb):
        """Local path returns error dict without attempting repair."""
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build.return_value = mock_envelope

        mock_client = MagicMock()
        mock_client.chat.return_value = _fake_chat_response(content="not json")
        mock_build.return_value = mock_client

        config = _make_agent_config()
        result = _call_ollama_json(
            None,
            config,
            PROMPT,
            CONTEXT,
            None,
            vendor_slug="ollama_local",
            cloud=False,
        )

        assert len(result) == 1
        assert result[0]["_parse_error"]
        assert result[0]["raw_response"] == "not json"

    def test_missing_api_key_raises_configuration_error(self):
        """_build_ollama_client(cloud=True) without api_key raises ConfigurationError."""
        config = _make_agent_config()
        with pytest.raises(ConfigurationError, match="ollama_cloud requires an API key"):
            _build_ollama_client(config, api_key=None, cloud=True)

    def test_missing_api_key_empty_string_raises_configuration_error(self):
        """Empty string api_key is treated as missing for cloud."""
        config = _make_agent_config()
        with pytest.raises(ConfigurationError, match="ollama_cloud requires an API key"):
            _build_ollama_client(config, api_key="", cloud=True)

    def test_base_url_defaults_to_ollama_com(self):
        """Cloud client defaults to https://ollama.com when no base_url provided."""
        config = _make_agent_config()
        with patch("agent_actions.llm.providers.ollama.client.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            _build_ollama_client(config, api_key="key-123", cloud=True)

            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["host"] == OllamaCloudDefaults.BASE_URL
            assert call_kwargs["host"] == "https://ollama.com"

    def test_base_url_from_config_overrides_default(self):
        """Cloud base_url in config overrides the default."""
        config = _make_agent_config(base_url="https://custom-ollama.example.com")
        with patch("agent_actions.llm.providers.ollama.client.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            _build_ollama_client(config, api_key="key-123", cloud=True)

            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["host"] == "https://custom-ollama.example.com"

    @patch.dict("os.environ", {"OLLAMA_CLOUD_HOST": "https://env-cloud.example.com"})
    def test_base_url_from_cloud_env(self):
        """OLLAMA_CLOUD_HOST env var is used for cloud when no config base_url."""
        config = _make_agent_config()
        with patch("agent_actions.llm.providers.ollama.client.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            _build_ollama_client(config, api_key="key-123", cloud=True)

            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["host"] == "https://env-cloud.example.com"

    def test_cloud_schema_injected_into_prompt(self):
        """Cloud JSON mode injects schema into the system message text.

        This is the positive counterpart to test_call_json_omits_format_param:
        cloud omits format param BUT injects the schema into the prompt so
        the model sees it. Without this, cloud JSON calls have no schema signal.
        """
        from agent_actions.prompt.message_builder import MessageBuilder

        schema = {
            "name": "test_schema",
            "schema": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
            },
        }
        envelope = MessageBuilder.build(
            "ollama_cloud",
            "Classify the item.",
            "A red apple",
            schema=schema,
            json_mode=True,
        )
        messages = envelope.to_dicts()
        # System message should contain the schema
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert system_msgs, "Expected a system message for ollama_cloud"
        system_text = system_msgs[0]["content"]
        assert "label" in system_text, "Schema field 'label' must appear in system message"
        assert "JSON" in system_text, "JSON instruction must appear in system message"

    def test_local_schema_not_in_prompt(self):
        """Local JSON mode does NOT inject schema into prompt (uses format param instead)."""
        from agent_actions.prompt.message_builder import MessageBuilder

        schema = {
            "name": "test_schema",
            "schema": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
            },
        }
        envelope = MessageBuilder.build(
            "ollama_local",
            "Classify the item.",
            "A red apple",
            schema=schema,
            json_mode=True,
        )
        messages = envelope.to_dicts()
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert system_msgs, "Expected a system message for ollama_local"
        system_text = system_msgs[0]["content"]
        # Local uses SchemaInjection.NONE — schema should NOT be in the prompt
        assert "required" not in system_text, "Local should not inject schema into prompt"


# ---------------------------------------------------------------------------
# OllamaBatchClient — vendor split
# ---------------------------------------------------------------------------


class TestOllamaBatchClientVendorSplit:
    """Batch client construction and invocation differences by cloud flag."""

    def test_cloud_validates_key_at_construction(self):
        """OllamaBatchClient(cloud=True) without api_key raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="ollama_cloud batch requires an API key"):
            OllamaBatchClient(cloud=True, vendor_slug="ollama_cloud")

    def test_cloud_empty_key_raises_configuration_error(self):
        """Empty string api_key also fails for cloud batch."""
        with pytest.raises(ConfigurationError, match="ollama_cloud batch requires an API key"):
            OllamaBatchClient(cloud=True, vendor_slug="ollama_cloud", api_key="")

    @patch("agent_actions.llm.providers.ollama.batch_client.Client")
    def test_local_no_key_required(self, mock_client_cls):
        """OllamaBatchClient(cloud=False) succeeds without api_key."""
        mock_client_cls.return_value = MagicMock()
        client = OllamaBatchClient(cloud=False, vendor_slug="ollama_local")
        assert client.cloud is False
        assert client.vendor_slug == "ollama_local"

    @patch("agent_actions.llm.providers.ollama.batch_client.Client")
    def test_cloud_client_has_bearer_header(self, mock_client_cls):
        """Cloud batch client constructs Client with Authorization header."""
        mock_client_cls.return_value = MagicMock()
        OllamaBatchClient(cloud=True, vendor_slug="ollama_cloud", api_key="batch-key")

        call_kwargs = mock_client_cls.call_args.kwargs
        assert "headers" in call_kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer batch-key"

    @patch("agent_actions.llm.providers.ollama.batch_client.Client")
    def test_local_client_no_bearer_header(self, mock_client_cls):
        """Local batch client constructs Client without Authorization header."""
        mock_client_cls.return_value = MagicMock()
        OllamaBatchClient(cloud=False, vendor_slug="ollama_local")

        call_kwargs = mock_client_cls.call_args
        if call_kwargs.kwargs:
            assert "headers" not in call_kwargs.kwargs

    @patch("agent_actions.llm.providers.ollama.batch_client.Client")
    @patch("agent_actions.llm.providers.ollama.batch_client.MessageBuilder")
    def test_vendor_slug_used_in_format_task(self, mock_mb, mock_client_cls):
        """format_task_for_provider passes vendor_slug to MessageBuilder.build_for_batch."""
        mock_client_cls.return_value = MagicMock()
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build_for_batch.return_value = mock_envelope

        batch_client = OllamaBatchClient(cloud=False, vendor_slug="ollama_local")

        from agent_actions.llm.providers.batch_base import BatchTask

        task = BatchTask(
            custom_id="req-1",
            prompt="Do something",
            user_content="data here",
            model_config={"model_name": "llama3"},
        )
        batch_client.format_task_for_provider(task)

        # MessageBuilder.build_for_batch should receive the vendor_slug
        build_call = mock_mb.build_for_batch.call_args
        assert build_call.args[0] == "ollama_local"

    @patch("agent_actions.llm.providers.ollama.batch_client.Client")
    @patch("agent_actions.llm.providers.ollama.batch_client.MessageBuilder")
    def test_cloud_vendor_slug_in_format_task(self, mock_mb, mock_client_cls):
        """Cloud batch client passes 'ollama_cloud' slug to MessageBuilder."""
        mock_client_cls.return_value = MagicMock()
        mock_envelope = MagicMock()
        mock_envelope.to_dicts.return_value = [{"role": "user", "content": "hi"}]
        mock_mb.build_for_batch.return_value = mock_envelope

        batch_client = OllamaBatchClient(cloud=True, vendor_slug="ollama_cloud", api_key="key-123")

        from agent_actions.llm.providers.batch_base import BatchTask

        task = BatchTask(
            custom_id="req-1",
            prompt="Do something",
            user_content="data here",
            model_config={"model_name": "llama3"},
        )
        batch_client.format_task_for_provider(task)

        build_call = mock_mb.build_for_batch.call_args
        assert build_call.args[0] == "ollama_cloud"

    @patch("agent_actions.llm.providers.ollama.batch_client.Client")
    def test_local_base_url_from_config(self, mock_client_cls):
        """OllamaBatchClient(base_url=..., cloud=False) passes the URL to Client(host=...)."""
        mock_client_cls.return_value = MagicMock()
        OllamaBatchClient(base_url="http://custom:11434", cloud=False, vendor_slug="ollama_local")

        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["host"] == "http://custom:11434"

    @patch("agent_actions.llm.providers.ollama.batch_client.Client")
    def test_cloud_base_url_defaults_to_ollama_com(self, mock_client_cls):
        """OllamaBatchClient(cloud=True) uses https://ollama.com as default host."""
        mock_client_cls.return_value = MagicMock()
        OllamaBatchClient(api_key="k", cloud=True, vendor_slug="ollama_cloud")

        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["host"] == "https://ollama.com"

    @patch("agent_actions.llm.providers.ollama.batch_client.Client")
    @patch.dict("os.environ", {"OLLAMA_CLOUD_HOST": "https://env-cloud.example.com"})
    def test_cloud_base_url_from_env(self, mock_client_cls):
        """OLLAMA_CLOUD_HOST env var is respected for cloud batch client."""
        mock_client_cls.return_value = MagicMock()
        OllamaBatchClient(api_key="k", cloud=True, vendor_slug="ollama_cloud")

        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["host"] == "https://env-cloud.example.com"
