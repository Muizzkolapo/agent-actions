"""Tests for Anthropic prompt caching: cache_control markers and the beta header."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.prompt.message_builder import (
    LLMMessage,
    LLMMessageEnvelope,
    MessageBuilder,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROMPT = "Analyse the sentiment."
CONTEXT = "I love this product!"
SCHEMA = [
    {
        "name": "sentiment_analysis",
        "description": "Analyse sentiment",
        "input_schema": {
            "type": "object",
            "properties": {"sentiment": {"type": "string"}},
            "required": ["sentiment"],
        },
    }
]
BETA_HEADER_KEY = "anthropic-beta"
BETA_HEADER_VALUE = "prompt-caching-2024-07-31"
CACHE_CONTROL_MARKER = {"type": "ephemeral"}


def _make_agent_config(*, enable_prompt_caching: bool = False, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "model_name": "claude-sonnet-4-20250514",
        "enable_prompt_caching": enable_prompt_caching,
    }
    config.update(overrides)
    return config


# ---------------------------------------------------------------------------
# MessageBuilder — cache_control injection
# ---------------------------------------------------------------------------


class TestMessageBuilderCacheControl:
    """MessageBuilder injects cache_control markers for Anthropic when enabled."""

    def test_anthropic_caching_enabled_adds_cache_control(self):
        """Messages include cache_control when caching is enabled for Anthropic."""
        envelope = MessageBuilder.build("anthropic", PROMPT, CONTEXT, enable_prompt_caching=True)
        assert len(envelope.messages) >= 1
        for msg in envelope.messages:
            assert msg.cache_control == CACHE_CONTROL_MARKER

    def test_anthropic_caching_disabled_no_cache_control(self):
        """Messages have no cache_control when caching is disabled."""
        envelope = MessageBuilder.build("anthropic", PROMPT, CONTEXT, enable_prompt_caching=False)
        for msg in envelope.messages:
            assert msg.cache_control is None

    def test_anthropic_caching_default_no_cache_control(self):
        """Default (omitted) enable_prompt_caching does not inject markers."""
        envelope = MessageBuilder.build("anthropic", PROMPT, CONTEXT)
        for msg in envelope.messages:
            assert msg.cache_control is None

    def test_non_anthropic_provider_caching_ignored(self):
        """cache_control is NOT injected for non-Anthropic providers."""
        for provider in (
            "openai",
            "groq",
            "cohere",
            "ollama_local",
            "ollama_cloud",
            "gemini",
        ):
            envelope = MessageBuilder.build(provider, PROMPT, CONTEXT, enable_prompt_caching=True)
            for msg in envelope.messages:
                assert msg.cache_control is None, f"{provider} should not get cache_control"

    def test_caching_preserves_message_content(self):
        """cache_control injection doesn't alter role or content."""
        without = MessageBuilder.build("anthropic", PROMPT, CONTEXT)
        with_cache = MessageBuilder.build("anthropic", PROMPT, CONTEXT, enable_prompt_caching=True)
        assert len(without.messages) == len(with_cache.messages)
        for orig, cached in zip(without.messages, with_cache.messages, strict=True):
            assert orig.role == cached.role
            assert orig.content == cached.content

    def test_caching_works_with_json_mode(self):
        """cache_control is injected regardless of json_mode setting."""
        for json_mode in (True, False):
            envelope = MessageBuilder.build(
                "anthropic",
                PROMPT,
                CONTEXT,
                json_mode=json_mode,
                enable_prompt_caching=True,
            )
            for msg in envelope.messages:
                assert msg.cache_control == CACHE_CONTROL_MARKER


# ---------------------------------------------------------------------------
# LLMMessage / LLMMessageEnvelope — to_dicts() with cache_control
# ---------------------------------------------------------------------------


class TestToDictsWithCacheControl:
    """to_dicts() formats structured content blocks when cache_control is set."""

    def test_no_cache_control_returns_simple_format(self):
        """Without cache_control, content is a plain string."""
        env = LLMMessageEnvelope(messages=[LLMMessage(role="user", content="hello")])
        dicts = env.to_dicts()
        assert dicts == [{"role": "user", "content": "hello"}]

    def test_cache_control_returns_structured_content_blocks(self):
        """With cache_control, content becomes a list of typed content blocks."""
        msg = LLMMessage(
            role="user", content="hello", cache_control={"type": "ephemeral"}, static_len=5
        )
        env = LLMMessageEnvelope(messages=[msg])
        dicts = env.to_dicts()
        assert len(dicts) == 1
        assert dicts[0]["role"] == "user"
        content = dicts[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 1
        assert content[0] == {
            "type": "text",
            "text": "hello",
            "cache_control": {"type": "ephemeral"},
        }

    def test_mixed_messages_format_independently(self):
        """Messages with and without cache_control format correctly together."""
        env = LLMMessageEnvelope(
            messages=[
                LLMMessage(
                    role="system", content="sys", cache_control={"type": "ephemeral"}, static_len=3
                ),
                LLMMessage(role="user", content="usr"),
            ]
        )
        dicts = env.to_dicts()
        # System message has structured content
        assert isinstance(dicts[0]["content"], list)
        assert dicts[0]["content"][0]["text"] == "sys"
        # User message has plain string
        assert dicts[1]["content"] == "usr"

    def test_role_filter_preserves_cache_control(self):
        """Filtering by role still returns structured content for cached messages."""
        env = LLMMessageEnvelope(
            messages=[
                LLMMessage(role="system", content="sys"),
                LLMMessage(
                    role="user", content="usr", cache_control={"type": "ephemeral"}, static_len=3
                ),
            ]
        )
        user_dicts = env.to_dicts(role="user")
        assert len(user_dicts) == 1
        assert isinstance(user_dicts[0]["content"], list)

    def test_a_mark_inside_the_text_splits_it_into_two_blocks(self):
        msg = LLMMessage(
            role="user", content="sharedrecord", cache_control={"type": "ephemeral"}, static_len=6
        )
        assert LLMMessageEnvelope(messages=[msg]).to_dicts() == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "shared", "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "record"},
                ],
            }
        ]

    def test_a_mark_with_no_prompt_text_before_it_is_refused(self):
        with pytest.raises(ValueError, match="static_len is 0"):
            LLMMessage(role="user", content="record", cache_control={"type": "ephemeral"})
        assert LLMMessage(role="user", content="record", static_len=0).cache_control is None

    def test_a_prompt_length_past_the_text_is_refused(self):
        with pytest.raises(ValueError, match="outside a content of length 6"):
            LLMMessage(role="user", content="record", static_len=7)


# ---------------------------------------------------------------------------
# AnthropicClient._build_api_args — header injection
# ---------------------------------------------------------------------------


class TestBuildApiArgs:
    """_build_api_args adds beta header when caching is enabled."""

    def test_caching_enabled_adds_beta_header(self):
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        messages = [{"role": "user", "content": "test"}]
        config = _make_agent_config()
        args = AnthropicClient._build_api_args(
            "claude-sonnet-4-20250514", messages, None, config, enable_prompt_caching=True
        )
        assert "extra_headers" in args
        assert args["extra_headers"][BETA_HEADER_KEY] == BETA_HEADER_VALUE

    def test_caching_disabled_no_beta_header(self):
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        messages = [{"role": "user", "content": "test"}]
        config = _make_agent_config()
        args = AnthropicClient._build_api_args(
            "claude-sonnet-4-20250514", messages, None, config, enable_prompt_caching=False
        )
        assert "extra_headers" not in args

    def test_caching_default_no_header(self):
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        messages = [{"role": "user", "content": "test"}]
        config = _make_agent_config()
        args = AnthropicClient._build_api_args("claude-sonnet-4-20250514", messages, None, config)
        assert "extra_headers" not in args

    def test_messages_passed_through(self):
        """Pre-built messages (including structured content) are passed as-is."""
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        structured = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}
                ],
            }
        ]
        config = _make_agent_config()
        args = AnthropicClient._build_api_args(
            "claude-sonnet-4-20250514", structured, None, config, enable_prompt_caching=True
        )
        assert args["messages"] == structured

    def test_schema_still_added_as_tools(self):
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        messages = [{"role": "user", "content": "test"}]
        config = _make_agent_config()
        args = AnthropicClient._build_api_args(
            "claude-sonnet-4-20250514", messages, SCHEMA, config, enable_prompt_caching=True
        )
        assert args["tools"] == SCHEMA
        assert "extra_headers" in args


# ---------------------------------------------------------------------------
# Full online flow — _call_api integration
# ---------------------------------------------------------------------------


class TestCallApiCachingIntegration:
    """_call_api reads enable_prompt_caching and produces correct API args."""

    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.ResponseBuilder")
    def test_caching_enabled_sends_header_and_markers(self, mock_rb, mock_fire, mock_anthropic):
        """Full flow: caching=True → beta header + structured content with cache_control."""
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="result")]
        mock_client.messages.create.return_value = mock_response

        config = _make_agent_config(enable_prompt_caching=True)
        AnthropicClient._call_api("test-key", config, PROMPT, {}, None)

        call_kwargs = mock_client.messages.create.call_args
        api_args = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]

        # Beta header present
        assert api_args.get("extra_headers", {}).get(BETA_HEADER_KEY) == BETA_HEADER_VALUE

        # Messages have structured content with cache_control
        messages = api_args["messages"]
        assert len(messages) >= 1
        content = messages[0]["content"]
        assert isinstance(content, list), "Content should be structured blocks"
        assert content[0]["cache_control"] == CACHE_CONTROL_MARKER

    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.ResponseBuilder")
    def test_caching_disabled_sends_plain_messages(self, mock_rb, mock_fire, mock_anthropic):
        """Full flow: caching=False → no header, plain string content."""
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="result")]
        mock_client.messages.create.return_value = mock_response

        config = _make_agent_config(enable_prompt_caching=False)
        AnthropicClient._call_api("test-key", config, PROMPT, {}, None)

        call_kwargs = mock_client.messages.create.call_args
        api_args = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]

        # No beta header
        assert "extra_headers" not in api_args

        # Messages have plain string content
        messages = api_args["messages"]
        assert isinstance(messages[0]["content"], str)

    @patch("agent_actions.llm.providers.anthropic.client.anthropic")
    @patch("agent_actions.llm.providers.anthropic.client.fire_event")
    @patch("agent_actions.llm.providers.anthropic.client.ResponseBuilder")
    def test_caching_with_schema_sends_tools_and_header(self, mock_rb, mock_fire, mock_anthropic):
        """Caching + schema: both tools and beta header present."""
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(input={"sentiment": "positive"})]
        mock_client.messages.create.return_value = mock_response

        config = _make_agent_config(enable_prompt_caching=True)
        AnthropicClient._call_api("test-key", config, PROMPT, {}, SCHEMA)

        call_kwargs = mock_client.messages.create.call_args
        api_args = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]

        assert "tools" in api_args, "Schema should be passed as tools"
        assert api_args.get("extra_headers", {}).get(BETA_HEADER_KEY) == BETA_HEADER_VALUE
        content = api_args["messages"][0]["content"]
        assert isinstance(content, list), "Content should be structured blocks"


# ---------------------------------------------------------------------------
# Batch envelope
# ---------------------------------------------------------------------------


class TestBatchClientNoRegression:
    """The batch envelope is marked for caching only when asked, by the online rule."""

    def test_batch_caching_marks_the_system_prompt_and_not_the_record(self):
        envelope = MessageBuilder.build_for_batch(
            "anthropic", PROMPT, CONTEXT, enable_prompt_caching=True
        )
        assert [msg.cache_control for msg in envelope.messages] == [CACHE_CONTROL_MARKER, None]

    def test_batch_caching_marks_nothing_for_another_provider(self):
        for provider in ("openai", "gemini"):
            envelope = MessageBuilder.build_for_batch(
                provider, PROMPT, CONTEXT, enable_prompt_caching=True
            )
            assert all(msg.cache_control is None for msg in envelope.messages), provider

    def test_batch_build_for_batch_no_cache_control(self):
        """Caching off by default: no message is marked."""
        envelope = MessageBuilder.build_for_batch("anthropic", PROMPT, CONTEXT)
        for msg in envelope.messages:
            assert msg.cache_control is None

    def test_batch_to_dicts_returns_plain_format(self):
        """Batch envelope.to_dicts() returns simple string content."""
        envelope = MessageBuilder.build_for_batch("anthropic", PROMPT, CONTEXT)
        dicts = envelope.to_dicts()
        for d in dicts:
            assert isinstance(d["content"], str)

    def test_batch_system_extraction_still_works(self):
        """Batch client pattern: to_dicts(role='system')[0]['content'] is a string."""
        envelope = MessageBuilder.build_for_batch("anthropic", PROMPT, CONTEXT)
        system_dicts = envelope.to_dicts(role="system")
        assert len(system_dicts) == 1
        assert isinstance(system_dicts[0]["content"], str)
        assert system_dicts[0]["content"] == PROMPT
