"""Unit tests for MetadataExtractor._extract_usage.

Covers OpenAI-style, Anthropic-style, zero-value, and explicit-None edge cases.
"""

import pytest

from agent_actions.utils.metadata.extractor import MetadataExtractor


class TestExtractUsageOpenAI:
    """OpenAI-style keys: prompt_tokens, completion_tokens, total_tokens."""

    @pytest.mark.parametrize(
        ("usage", "expected"),
        [
            pytest.param(
                {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                id="standard",
            ),
            pytest.param(
                {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                id="explicit-none-coerced-to-zero",
            ),
        ],
    )
    def test_openai_usage(self, usage, expected):
        assert MetadataExtractor._extract_usage({"usage": usage}) == expected

    def test_zero_prompt_tokens_preserved(self):
        """Zero should not fall through to Anthropic keys."""
        response = {"usage": {"prompt_tokens": 0, "completion_tokens": 5, "total_tokens": 5}}
        result = MetadataExtractor._extract_usage(response)
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 5


class TestExtractUsageAnthropic:
    """Anthropic-style keys: input_tokens, output_tokens."""

    @pytest.mark.parametrize(
        ("usage", "expected"),
        [
            pytest.param(
                {"input_tokens": 5, "output_tokens": 10},
                {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                id="standard",
            ),
            pytest.param(
                {"input_tokens": None, "output_tokens": None},
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                id="explicit-none-coerced-to-zero",
            ),
        ],
    )
    def test_anthropic_usage(self, usage, expected):
        assert MetadataExtractor._extract_usage({"usage": usage}) == expected

    def test_zero_input_tokens(self):
        response = {"usage": {"input_tokens": 0, "output_tokens": 7}}
        result = MetadataExtractor._extract_usage(response)
        assert result["prompt_tokens"] == 0
        assert result["total_tokens"] == 7


class TestExtractUsageEdgeCases:
    """Edge cases: missing usage, empty dict, non-dict."""

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param({}, id="no-usage-key"),
            pytest.param({"usage": None}, id="usage-none"),
            pytest.param({"usage": "invalid"}, id="usage-not-dict"),
        ],
    )
    def test_no_usable_usage_returns_none(self, response):
        assert MetadataExtractor._extract_usage(response) is None

    def test_total_tokens_computed_when_missing(self):
        response = {"usage": {"prompt_tokens": 3, "completion_tokens": 7}}
        result = MetadataExtractor._extract_usage(response)
        assert result["total_tokens"] == 10
