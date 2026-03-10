"""Unit tests for MetadataExtractor._extract_usage.

Covers OpenAI-style, Anthropic-style, zero-value, and explicit-None edge cases.
"""

from agent_actions.utils.metadata.extractor import MetadataExtractor


class TestExtractUsageOpenAI:
    """OpenAI-style keys: prompt_tokens, completion_tokens, total_tokens."""

    def test_standard_openai_usage(self):
        response = {"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}
        result = MetadataExtractor._extract_usage(response)
        assert result == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

    def test_zero_prompt_tokens_preserved(self):
        """Zero should not fall through to Anthropic keys."""
        response = {"usage": {"prompt_tokens": 0, "completion_tokens": 5, "total_tokens": 5}}
        result = MetadataExtractor._extract_usage(response)
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 5

    def test_explicit_none_prompt_tokens(self):
        """Explicit None from provider should be coerced to 0."""
        response = {
            "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
        }
        result = MetadataExtractor._extract_usage(response)
        assert result == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


class TestExtractUsageAnthropic:
    """Anthropic-style keys: input_tokens, output_tokens."""

    def test_standard_anthropic_usage(self):
        response = {"usage": {"input_tokens": 5, "output_tokens": 10}}
        result = MetadataExtractor._extract_usage(response)
        assert result == {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15}

    def test_zero_input_tokens(self):
        response = {"usage": {"input_tokens": 0, "output_tokens": 7}}
        result = MetadataExtractor._extract_usage(response)
        assert result["prompt_tokens"] == 0
        assert result["total_tokens"] == 7

    def test_explicit_none_input_tokens(self):
        """Explicit None from provider should be coerced to 0."""
        response = {"usage": {"input_tokens": None, "output_tokens": None}}
        result = MetadataExtractor._extract_usage(response)
        assert result == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


class TestExtractUsageEdgeCases:
    """Edge cases: missing usage, empty dict, non-dict."""

    def test_no_usage_key(self):
        assert MetadataExtractor._extract_usage({}) is None

    def test_usage_is_none(self):
        assert MetadataExtractor._extract_usage({"usage": None}) is None

    def test_usage_is_not_dict(self):
        assert MetadataExtractor._extract_usage({"usage": "invalid"}) is None

    def test_total_tokens_computed_when_missing(self):
        response = {"usage": {"prompt_tokens": 3, "completion_tokens": 7}}
        result = MetadataExtractor._extract_usage(response)
        assert result["total_tokens"] == 10
