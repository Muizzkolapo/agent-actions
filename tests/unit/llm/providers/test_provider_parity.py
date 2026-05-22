"""Tests for provider parity fixes (P2-3).

Issue 2: Groq should not inject temperature=0.7 default.
Issue 3: Anthropic max_tokens default should be 4096 (not 1024).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.groq.client import GroqClient


def _setup_groq_mocks(mock_mb, mock_groq_cls):
    """Wire Groq mocks and return mock_client for call_args inspection."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_envelope = MagicMock()
    mock_envelope.to_dicts.return_value = [{"role": "user", "content": "test"}]
    mock_mb.build.return_value = mock_envelope

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "plain text"
    response.usage = MagicMock(prompt_tokens=5, completion_tokens=10, total_tokens=15)
    response.model = "llama3-8b-8192"
    mock_client.chat.completions.create.return_value = response
    return mock_client


def _call_groq_non_json(agent_config=None):
    """Call GroqClient.call_non_json with default args."""
    GroqClient.call_non_json(
        api_key="test-key",
        agent_config=agent_config or {"model_name": "llama3-8b-8192"},
        prompt_config="test prompt",
        context_data={"key": "val"},
    )


class TestGroqTemperatureDefault:
    """Groq must not inject a temperature default — only max_tokens."""

    @patch("agent_actions.llm.providers.groq.client.Groq")
    @patch("agent_actions.llm.providers.groq.client.MessageBuilder")
    def test_no_temperature_injected_when_absent(self, mock_mb, mock_groq_cls):
        mock_client = _setup_groq_mocks(mock_mb, mock_groq_cls)
        _call_groq_non_json()

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "temperature" not in call_kwargs

    @patch("agent_actions.llm.providers.groq.client.Groq")
    @patch("agent_actions.llm.providers.groq.client.MessageBuilder")
    def test_user_temperature_preserved(self, mock_mb, mock_groq_cls):
        mock_client = _setup_groq_mocks(mock_mb, mock_groq_cls)
        _call_groq_non_json({"model_name": "llama3-8b-8192", "temperature": 0.3})

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.3

    @patch("agent_actions.llm.providers.groq.client.Groq")
    @patch("agent_actions.llm.providers.groq.client.MessageBuilder")
    def test_max_tokens_default_preserved(self, mock_mb, mock_groq_cls):
        """max_tokens=1000 default must remain — required by Groq API."""
        mock_client = _setup_groq_mocks(mock_mb, mock_groq_cls)
        _call_groq_non_json()

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 1000


class TestAnthropicMaxTokensDefault:
    """Anthropic max_tokens default should be 4096, not 1024."""

    def test_default_max_tokens_is_4096(self):
        api_args = AnthropicClient._build_api_args(
            model_name="claude-3-sonnet-20240229",
            messages=[{"role": "user", "content": "test"}],
            schema=None,
            agent_config={},
        )
        assert api_args["max_tokens"] == 4096

    def test_user_max_tokens_not_overridden(self):
        api_args = AnthropicClient._build_api_args(
            model_name="claude-3-sonnet-20240229",
            messages=[{"role": "user", "content": "test"}],
            schema=None,
            agent_config={"max_tokens": 8192},
        )
        assert api_args["max_tokens"] == 8192

    def test_user_max_tokens_lower_than_default_preserved(self):
        """setdefault respects user values even below the default."""
        api_args = AnthropicClient._build_api_args(
            model_name="claude-3-sonnet-20240229",
            messages=[{"role": "user", "content": "test"}],
            schema=None,
            agent_config={"max_tokens": 512},
        )
        assert api_args["max_tokens"] == 512
