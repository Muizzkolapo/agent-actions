"""Tests for ResponseBuilder — output wrapping and usage extraction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agent_actions.output.response.response_builder import (
    ResponseBuilder,
    UsageResult,
)

# ---------------------------------------------------------------------------
# Helpers — mock response objects matching each provider's SDK shape
# ---------------------------------------------------------------------------


def _openai_response(prompt=10, completion=20, total=30):
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=total
        )
    )


def _anthropic_response(input_t=10, output_t=20):
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=input_t, output_tokens=output_t))


def _gemini_response(prompt=10, candidates=20, total=30):
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=candidates, total_token_count=total
        )
    )


def _cohere_response(input_t=10, output_t=20):
    return SimpleNamespace(
        usage=SimpleNamespace(tokens=SimpleNamespace(input_tokens=input_t, output_tokens=output_t))
    )


def _ollama_response(prompt_eval=10, eval_count=20):
    return SimpleNamespace(prompt_eval_count=prompt_eval, eval_count=eval_count)


# ---------------------------------------------------------------------------
# Tests — wrap_non_json
# ---------------------------------------------------------------------------


class TestWrapNonJson:
    """Test output field wrapping."""

    def test_default_output_field(self):
        result = ResponseBuilder.wrap_non_json("hello", {})
        assert result == [{"raw_response": "hello"}]

    def test_custom_output_field(self):
        result = ResponseBuilder.wrap_non_json("hello", {"output_field": "summary"})
        assert result == [{"summary": "hello"}]

    def test_empty_content(self):
        result = ResponseBuilder.wrap_non_json("", {})
        assert result == [{"raw_response": ""}]

    def test_returns_list_of_one_dict(self):
        result = ResponseBuilder.wrap_non_json("text", {})
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)


# ---------------------------------------------------------------------------
# Tests — extract_usage per shape
# ---------------------------------------------------------------------------


class TestExtractUsage:
    """Test usage extraction for all 6 shapes."""

    def test_openai_compat(self):
        resp = _openai_response(10, 20, 30)
        usage = ResponseBuilder.extract_usage(resp, "openai")
        assert usage == UsageResult(10, 20, 30)

    def test_openai_compat_groq(self):
        resp = _openai_response(5, 15, 20)
        usage = ResponseBuilder.extract_usage(resp, "groq")
        assert usage == UsageResult(5, 15, 20)

    def test_openai_compat_mistral(self):
        resp = _openai_response(8, 12, 20)
        usage = ResponseBuilder.extract_usage(resp, "mistral")
        assert usage == UsageResult(8, 12, 20)

    def test_anthropic(self):
        resp = _anthropic_response(10, 20)
        usage = ResponseBuilder.extract_usage(resp, "anthropic")
        assert usage == UsageResult(10, 20, 30)

    def test_gemini(self):
        resp = _gemini_response(10, 20, 30)
        usage = ResponseBuilder.extract_usage(resp, "gemini")
        assert usage == UsageResult(10, 20, 30)

    def test_cohere(self):
        resp = _cohere_response(10, 20)
        usage = ResponseBuilder.extract_usage(resp, "cohere")
        assert usage == UsageResult(10, 20, 30)

    def test_ollama(self):
        resp = _ollama_response(10, 20)
        usage = ResponseBuilder.extract_usage(resp, "ollama")
        assert usage == UsageResult(10, 20, 30)

    def test_none_shape(self):
        usage = ResponseBuilder.extract_usage(None, "agac-fake-provider")
        assert usage == UsageResult(0, 0, 0)

    def test_unknown_provider_returns_zeros(self):
        usage = ResponseBuilder.extract_usage(None, "nonexistent")
        assert usage == UsageResult(0, 0, 0)


# ---------------------------------------------------------------------------
# Tests — extract_usage edge cases (missing/None usage)
# ---------------------------------------------------------------------------


class TestExtractUsageEdgeCases:
    """Test graceful handling of missing or None usage data."""

    def test_openai_no_usage(self):
        resp = SimpleNamespace(usage=None)
        usage = ResponseBuilder.extract_usage(resp, "openai")
        assert usage == UsageResult(0, 0, 0)

    def test_anthropic_no_usage(self):
        resp = SimpleNamespace(usage=None)
        usage = ResponseBuilder.extract_usage(resp, "anthropic")
        assert usage == UsageResult(0, 0, 0)

    def test_gemini_no_usage_metadata(self):
        resp = SimpleNamespace()  # no usage_metadata attribute
        usage = ResponseBuilder.extract_usage(resp, "gemini")
        assert usage == UsageResult(0, 0, 0)

    def test_gemini_none_usage_metadata(self):
        resp = SimpleNamespace(usage_metadata=None)
        usage = ResponseBuilder.extract_usage(resp, "gemini")
        assert usage == UsageResult(0, 0, 0)

    def test_cohere_no_usage(self):
        resp = SimpleNamespace()  # no usage attribute
        usage = ResponseBuilder.extract_usage(resp, "cohere")
        assert usage == UsageResult(0, 0, 0)

    def test_cohere_no_tokens(self):
        resp = SimpleNamespace(usage=SimpleNamespace(tokens=None))
        usage = ResponseBuilder.extract_usage(resp, "cohere")
        assert usage == UsageResult(0, 0, 0)

    def test_ollama_missing_attrs(self):
        resp = SimpleNamespace()  # no prompt_eval_count or eval_count
        usage = ResponseBuilder.extract_usage(resp, "ollama")
        assert usage == UsageResult(0, 0, 0)

    def test_ollama_none_values(self):
        resp = SimpleNamespace(prompt_eval_count=None, eval_count=None)
        usage = ResponseBuilder.extract_usage(resp, "ollama")
        assert usage == UsageResult(0, 0, 0)


# ---------------------------------------------------------------------------
# Tests — record_usage_and_event
# ---------------------------------------------------------------------------


class TestRecordUsageAndEvent:
    """Test the combined usage + storage + event method."""

    @patch("agent_actions.output.response.response_builder.set_last_usage")
    @patch("agent_actions.output.response.response_builder.fire_event")
    def test_stores_usage_and_fires_event(self, mock_fire, mock_set):
        resp = _openai_response(10, 20, 30)
        usage = ResponseBuilder.record_usage_and_event(resp, "openai", "gpt-4", 150.0, "req-123")
        assert usage == UsageResult(10, 20, 30)
        mock_set.assert_called_once_with(
            {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
            }
        )
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert event.provider == "openai"
        assert event.model == "gpt-4"
        assert event.prompt_tokens == 10
        assert event.completion_tokens == 20
        assert event.total_tokens == 30
        assert event.latency_ms == 150.0
        assert event.request_id == "req-123"

    @patch("agent_actions.output.response.response_builder.set_last_usage")
    @patch("agent_actions.output.response.response_builder.fire_event")
    def test_skips_set_last_usage_for_zero_tokens(self, mock_fire, mock_set):
        usage = ResponseBuilder.record_usage_and_event(
            None, "agac-fake-provider", "mock", 0.0, "req-0"
        )
        assert usage == UsageResult(0, 0, 0)
        mock_set.assert_not_called()
        # Event still fires with zero tokens
        mock_fire.assert_called_once()
        event = mock_fire.call_args[0][0]
        assert event.prompt_tokens == 0
        assert event.completion_tokens == 0
        assert event.total_tokens == 0
        assert event.provider == "agac-fake-provider"

    @patch("agent_actions.output.response.response_builder.set_last_usage")
    @patch("agent_actions.output.response.response_builder.fire_event")
    def test_returns_usage_result(self, mock_fire, mock_set):
        resp = _anthropic_response(5, 15)
        usage = ResponseBuilder.record_usage_and_event(
            resp, "anthropic", "claude-3", 200.0, "req-456"
        )
        assert usage.prompt_tokens == 5
        assert usage.completion_tokens == 15
        assert usage.total_tokens == 20


# ---------------------------------------------------------------------------
# Tests — additional edge cases from PR review
# ---------------------------------------------------------------------------


class TestAdditionalEdgeCases:
    """Cover gaps identified in PR review."""

    def test_extract_openai_compat_none_response(self):
        """_extract_openai_compat handles None response without AttributeError."""
        usage = ResponseBuilder.extract_usage(None, "openai")
        assert usage == UsageResult(0, 0, 0)

    def test_extract_anthropic_none_response(self):
        """_extract_anthropic handles None response without AttributeError."""
        usage = ResponseBuilder.extract_usage(None, "anthropic")
        assert usage == UsageResult(0, 0, 0)

    def test_wrap_non_json_none_content(self):
        """wrap_non_json with None content produces {output_field: None}."""
        result = ResponseBuilder.wrap_non_json(None, {})
        assert result == [{"raw_response": None}]

    def test_extract_cohere_usage_attr_exists_but_falsy(self):
        """Cohere with usage=0 (falsy but present) returns zeros."""
        resp = SimpleNamespace(usage=0)
        usage = ResponseBuilder.extract_usage(resp, "cohere")
        assert usage == UsageResult(0, 0, 0)
