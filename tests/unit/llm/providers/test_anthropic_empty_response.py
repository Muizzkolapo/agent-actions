"""Tests for Anthropic empty response handling (Defect 4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.anthropic.client import AnthropicClient


def _make_empty_response(text="No structured output", stop_reason="end_turn"):
    """Create a mock Anthropic response with no 'input' block."""
    text_block = MagicMock()
    text_block.text = text
    del text_block.input  # no input attribute

    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = stop_reason
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
        assert "stop_reason=end_turn" in result[0]["_parse_error"]
        assert "No structured output" in result[0]["_parse_error"]
        assert result[0]["raw_response"] == "No structured output"

    @patch.object(AnthropicClient, "_call_api")
    def test_max_tokens_and_text_answer_are_told_apart(self, mock_call_api):
        """The stop reason in _parse_error separates truncation from a text answer."""
        outcomes = {}
        for stop_reason in ("max_tokens", "end_turn"):
            mock_call_api.return_value = (
                _make_empty_response("The decision is approve.", stop_reason),
                "claude-3-sonnet-20240229",
                "req-1",
            )
            outcomes[stop_reason] = AnthropicClient.call_json(
                api_key="k",
                agent_config={"model_name": "claude-3-sonnet-20240229"},
                prompt_config="p",
                context_data={},
                schema=None,
            )[0]["_parse_error"]

        assert "stop_reason=max_tokens" in outcomes["max_tokens"]
        assert "stop_reason=end_turn" in outcomes["end_turn"]
        assert outcomes["max_tokens"] != outcomes["end_turn"]

    @patch.object(AnthropicClient, "_call_api")
    def test_response_without_text_still_reports_stop_reason(self, mock_call_api):
        """A response of only thinking blocks has no text but keeps its stop reason."""
        thinking = MagicMock(spec=["thinking", "type"])
        response = MagicMock()
        response.content = [thinking]
        response.stop_reason = "max_tokens"
        mock_call_api.return_value = (response, "claude-3-sonnet-20240229", "req-2")

        result = AnthropicClient.call_json(
            api_key="k",
            agent_config={"model_name": "claude-3-sonnet-20240229"},
            prompt_config="p",
            context_data={},
            schema=None,
        )

        assert "stop_reason=max_tokens" in result[0]["_parse_error"]
        assert result[0]["raw_response"] == ""

    @patch.object(AnthropicClient, "_call_api")
    def test_long_text_is_truncated_in_message_but_kept_in_raw_response(self, mock_call_api):
        text = "x" * 1000
        mock_call_api.return_value = (
            _make_empty_response(text),
            "claude-3-sonnet-20240229",
            "req-3",
        )

        result = AnthropicClient.call_json(
            api_key="k",
            agent_config={"model_name": "claude-3-sonnet-20240229"},
            prompt_config="p",
            context_data={},
            schema=None,
        )

        assert len(result[0]["_parse_error"]) < 400
        assert result[0]["raw_response"] == text

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
