"""Tests for OpenAI JSON parse failure with reprompt (Defect 5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import LLMResponseParseError
from agent_actions.llm.providers.openai.client import OpenAIClient


def _make_response(content: str):
    """Create a mock OpenAI response with given content."""
    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    response.model = "gpt-4"
    return response


class TestOpenAIParseFailureReprompt:
    """Defect 5: JSON parse failure raises when reprompt is configured."""

    @patch("agent_actions.llm.providers.openai.client.OpenAI")
    def test_parse_failure_with_reprompt_raises(self, mock_openai_cls):
        """When reprompt is configured, parse failure raises LLMResponseParseError."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_response(
            "this is not valid json {"
        )

        agent_config = {
            "model_name": "gpt-4",
            "reprompt": {"max_attempts": 3},
        }
        with pytest.raises(LLMResponseParseError, match="Failed to parse JSON"):
            OpenAIClient.call_json(
                api_key="test-key",
                agent_config=agent_config,
                prompt_config="extract data",
                context_data={"text": "hello"},
                schema=None,
            )

    @patch("agent_actions.llm.providers.openai.client.OpenAI")
    def test_parse_failure_without_reprompt_returns_sentinel(self, mock_openai_cls):
        """Without reprompt config, parse failure returns _parse_error sentinel."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_response(
            "this is not valid json {"
        )

        agent_config = {
            "model_name": "gpt-4",
        }
        result = OpenAIClient.call_json(
            api_key="test-key",
            agent_config=agent_config,
            prompt_config="extract data",
            context_data={"text": "hello"},
            schema=None,
        )

        assert len(result) == 1
        assert "_parse_error" in result[0]
        assert "raw_response" in result[0]

    @patch("agent_actions.llm.providers.openai.client.OpenAI")
    def test_valid_json_response_unaffected(self, mock_openai_cls):
        """Valid JSON responses are unaffected regardless of reprompt config."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_response(
            '{"sentiment": "positive"}'
        )

        agent_config = {
            "model_name": "gpt-4",
            "reprompt": {"max_attempts": 3},
        }
        result = OpenAIClient.call_json(
            api_key="test-key",
            agent_config=agent_config,
            prompt_config="extract data",
            context_data={"text": "hello"},
            schema=None,
        )

        assert len(result) == 1
        assert result[0]["sentiment"] == "positive"

    @patch("agent_actions.llm.providers.openai.client.OpenAI")
    def test_empty_response_with_reprompt_returns_sentinel(self, mock_openai_cls):
        """Empty response returns sentinel even with reprompt (not a parse failure)."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_response(None)

        agent_config = {
            "model_name": "gpt-4",
            "reprompt": {"max_attempts": 3},
        }
        result = OpenAIClient.call_json(
            api_key="test-key",
            agent_config=agent_config,
            prompt_config="extract data",
            context_data={"text": "hello"},
            schema=None,
        )

        assert len(result) == 1
        assert result[0]["_parse_error"] == "Empty response from API"

    @patch("agent_actions.llm.providers.openai.client.OpenAI")
    def test_parse_error_context_includes_snippet(self, mock_openai_cls):
        """LLMResponseParseError context includes response snippet."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_response("invalid json content")

        agent_config = {
            "model_name": "gpt-4",
            "reprompt": {"max_attempts": 3},
        }
        with pytest.raises(LLMResponseParseError) as exc_info:
            OpenAIClient.call_json(
                api_key="test-key",
                agent_config=agent_config,
                prompt_config="extract data",
                context_data={"text": "hello"},
                schema=None,
            )
        assert "raw_response_snippet" in exc_info.value.context
