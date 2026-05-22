"""Tests for Anthropic empty response handling (Defect 4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.anthropic.client import AnthropicClient


def _make_empty_response():
    """Create a mock Anthropic response with no 'input' block."""
    text_block = MagicMock()
    text_block.text = "No structured output"
    del text_block.input  # no input attribute

    response = MagicMock()
    response.content = [text_block]
    response.usage = MagicMock(input_tokens=10, output_tokens=5)
    response.model = "claude-3-sonnet-20240229"
    return response


def _make_valid_response(data: dict):
    """Create a mock Anthropic response with a valid 'input' block."""
    input_block = MagicMock()
    input_block.input = data

    response = MagicMock()
    response.content = [input_block]
    response.usage = MagicMock(input_tokens=10, output_tokens=5)
    response.model = "claude-3-sonnet-20240229"
    return response


class TestAnthropicEmptyResponseSentinel:
    """Defect 4: Empty Anthropic responses return _parse_error sentinel."""

    @patch.object(AnthropicClient, "_call_api")
    def test_empty_response_returns_parse_error_sentinel(self, mock_call_api):
        """Empty response returns _parse_error dict instead of raising."""
        mock_call_api.return_value = (
            _make_empty_response(),
            "claude-3-sonnet-20240229",
            "req-123",
        )

        result = AnthropicClient.call_json(
            api_key="test-key",
            agent_config={"model_name": "claude-3-sonnet-20240229"},
            prompt_config="test prompt",
            context_data={"key": "val"},
            schema=None,
        )

        assert len(result) == 1
        assert result[0]["_parse_error"] == "Empty response from API"
        assert result[0]["raw_response"] == ""

    @patch.object(AnthropicClient, "_call_api")
    def test_valid_response_unchanged(self, mock_call_api):
        """Valid response with input block is returned as before."""
        mock_call_api.return_value = (
            _make_valid_response({"sentiment": "positive"}),
            "claude-3-sonnet-20240229",
            "req-456",
        )

        result = AnthropicClient.call_json(
            api_key="test-key",
            agent_config={"model_name": "claude-3-sonnet-20240229"},
            prompt_config="test prompt",
            context_data={"key": "val"},
            schema=None,
        )

        assert len(result) == 1
        assert result[0]["sentiment"] == "positive"

    @patch.object(AnthropicClient, "_call_api")
    def test_sentinel_matches_openai_format(self, mock_call_api):
        """Sentinel format matches OpenAI: raw_response + _parse_error keys."""
        mock_call_api.return_value = (
            _make_empty_response(),
            "claude-3-sonnet-20240229",
            "req-789",
        )

        result = AnthropicClient.call_json(
            api_key="test-key",
            agent_config={"model_name": "claude-3-sonnet-20240229"},
            prompt_config="test",
            context_data={},
            schema=None,
        )

        assert set(result[0].keys()) == {"raw_response", "_parse_error"}
