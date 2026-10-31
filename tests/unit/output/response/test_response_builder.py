"""Tests for ResponseBuilder — output wrapping and usage extraction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

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


class TestUnwrap:
    """The counterpart to wrap_non_json, over the shapes providers return."""

    def test_round_trips_wrap_non_json(self):
        assert ResponseBuilder.unwrap(ResponseBuilder.wrap_non_json("hello", {}), {}) == "hello"

    def test_round_trips_a_custom_output_field(self):
        config = {"output_field": "summary"}
        wrapped = ResponseBuilder.wrap_non_json("hello", config)
        assert ResponseBuilder.unwrap(wrapped, config) == "hello"

    def test_an_already_parsed_object_comes_back_whole(self):
        parsed = {"passed": True, "reason": "ok"}
        assert ResponseBuilder.unwrap([parsed], {}) == parsed

    def test_a_parse_error_envelope_yields_its_empty_text(self):
        envelope = [{"raw_response": "", "_parse_error": "Empty response from API"}]
        assert ResponseBuilder.unwrap(envelope, {}) == ""

    def test_a_bare_string_element_is_returned_as_is(self):
        assert ResponseBuilder.unwrap(["plain text"], {}) == "plain text"

    def test_an_empty_or_non_list_result_has_no_payload(self):
        assert ResponseBuilder.unwrap([], {}) is None
        assert ResponseBuilder.unwrap({"passed": True}, {}) is None
        assert ResponseBuilder.unwrap("yes", {}) is None

    def test_only_the_first_element_is_read(self):
        assert ResponseBuilder.unwrap([{"raw_response": "a"}, {"raw_response": "b"}], {}) == "a"


# ---------------------------------------------------------------------------
# Tests — extract_usage per shape
# ---------------------------------------------------------------------------


class TestExtractUsage:
    """Test usage extraction for all 6 shapes."""

    @pytest.mark.parametrize(
        ("resp", "provider", "expected"),
        [
            pytest.param(
                _openai_response(10, 20, 30), "openai", UsageResult(10, 20, 30), id="openai"
            ),
            pytest.param(_openai_response(5, 15, 20), "groq", UsageResult(5, 15, 20), id="groq"),
            pytest.param(
                _anthropic_response(10, 20), "anthropic", UsageResult(10, 20, 30), id="anthropic"
            ),
            pytest.param(
                _gemini_response(10, 20, 30), "gemini", UsageResult(10, 20, 30), id="gemini"
            ),
            pytest.param(_cohere_response(10, 20), "cohere", UsageResult(10, 20, 30), id="cohere"),
            pytest.param(
                _ollama_response(10, 20), "ollama_local", UsageResult(10, 20, 30), id="ollama"
            ),
        ],
    )
    def test_reads_each_provider_shape(self, resp, provider, expected):
        assert ResponseBuilder.extract_usage(resp, provider) == expected


# ---------------------------------------------------------------------------
# Tests — extract_usage edge cases (missing/None usage)
# ---------------------------------------------------------------------------


class TestExtractUsageEdgeCases:
    """Test graceful handling of missing or None usage data."""

    @pytest.mark.parametrize(
        ("resp", "provider"),
        [
            pytest.param(SimpleNamespace(usage=None), "openai", id="openai-no-usage"),
            pytest.param(SimpleNamespace(usage=None), "anthropic", id="anthropic-no-usage"),
            pytest.param(SimpleNamespace(), "gemini", id="gemini-no-usage-metadata"),
            pytest.param(SimpleNamespace(usage_metadata=None), "gemini", id="gemini-none-metadata"),
            pytest.param(SimpleNamespace(), "cohere", id="cohere-no-usage"),
            pytest.param(
                SimpleNamespace(usage=SimpleNamespace(tokens=None)), "cohere", id="cohere-no-tokens"
            ),
            pytest.param(SimpleNamespace(usage=0), "cohere", id="cohere-falsy-usage"),
            pytest.param(SimpleNamespace(), "ollama_local", id="ollama-missing-attrs"),
            pytest.param(
                SimpleNamespace(prompt_eval_count=None, eval_count=None),
                "ollama_local",
                id="ollama-none-values",
            ),
            pytest.param(None, "openai", id="openai-none-response"),
            pytest.param(None, "anthropic", id="anthropic-none-response"),
            pytest.param(None, "agac-fake-provider", id="none-shape"),
            pytest.param(None, "nonexistent", id="unknown-provider"),
        ],
    )
    def test_returns_zeros(self, resp, provider):
        assert ResponseBuilder.extract_usage(resp, provider) == UsageResult(0, 0, 0)


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

    def test_wrap_non_json_none_content(self):
        """wrap_non_json with None content produces {output_field: None}."""
        result = ResponseBuilder.wrap_non_json(None, {})
        assert result == [{"raw_response": None}]
