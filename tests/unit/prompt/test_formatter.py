"""Regression tests for PromptFormatter — B-3: empty-string prompt guard."""

from unittest.mock import patch

import pytest

from agent_actions.errors import ConfigValidationError, PromptValidationError
from agent_actions.prompt.formatter import PromptFormatter


class TestGetRawPromptEmptyString:
    """Empty-string prompt must raise ConfigValidationError (B-3)."""

    def test_empty_string_raises_config_validation_error(self):
        with pytest.raises(ConfigValidationError, match="empty string"):
            PromptFormatter.get_raw_prompt({"prompt": ""})

    def test_whitespace_only_raises_config_validation_error(self):
        with pytest.raises(ConfigValidationError, match="empty string"):
            PromptFormatter.get_raw_prompt({"prompt": "   "})

    def test_tab_only_raises_config_validation_error(self):
        with pytest.raises(ConfigValidationError, match="empty string"):
            PromptFormatter.get_raw_prompt({"prompt": "\t"})

    def test_newline_only_raises_config_validation_error(self):
        with pytest.raises(ConfigValidationError, match="empty string"):
            PromptFormatter.get_raw_prompt({"prompt": "\n"})

    def test_none_prompt_returns_default(self):
        result = PromptFormatter.get_raw_prompt({"prompt": None})
        assert result == "Process the following content: {content}"

    def test_missing_prompt_key_returns_default(self):
        result = PromptFormatter.get_raw_prompt({})
        assert result == "Process the following content: {content}"

    def test_valid_prompt_returned(self):
        result = PromptFormatter.get_raw_prompt({"prompt": "Do something useful."})
        assert result == "Do something useful."

    def test_tool_kind_empty_prompt_does_not_raise(self):
        # kind: tool actions have no prompt — empty/whitespace must not raise
        result = PromptFormatter.get_raw_prompt({"kind": "tool", "prompt": ""})
        assert result == "Process the following content: {content}"

    def test_tool_kind_whitespace_prompt_does_not_raise(self):
        # tool actions are exempt — whitespace prompt must not raise;
        # whitespace is truthy so the raw value is returned as-is
        result = PromptFormatter.get_raw_prompt({"kind": "tool", "prompt": "   "})
        assert result == "   "

    def test_hitl_kind_empty_prompt_does_not_raise(self):
        # kind:hitl has no prompt field — empty string falls through to default
        result = PromptFormatter.get_raw_prompt({"kind": "hitl", "prompt": ""})
        assert result == "Process the following content: {content}"

    def test_seed_kind_empty_prompt_does_not_raise(self):
        # kind:seed has no prompt field — whitespace is returned as-is
        result = PromptFormatter.get_raw_prompt({"kind": "seed", "prompt": "   "})
        assert result == "   "

    def test_source_kind_empty_prompt_does_not_raise(self):
        # kind:source is a workflow input action with no prompt field
        result = PromptFormatter.get_raw_prompt({"kind": "source", "prompt": ""})
        assert result == "Process the following content: {content}"

    def test_non_string_prompt_returns_raw_value(self):
        # A mis-configured numeric prompt bypasses the string guard and is
        # returned unchanged (pre-existing behaviour, documented by this test).
        result = PromptFormatter.get_raw_prompt({"prompt": 42})
        assert result == 42

    def test_dollar_prompt_load_failure_raises_prompt_validation_error(self):
        # When a $-prefixed prompt reference cannot be loaded, the except branch
        # wraps the failure in PromptValidationError (not the raw underlying error).
        with patch(
            "agent_actions.prompt.formatter.PromptLoader.load_prompt",
            side_effect=FileNotFoundError("prompt file missing"),
        ):
            with pytest.raises(PromptValidationError):
                PromptFormatter.get_raw_prompt({"prompt": "$my_workflow.My_Prompt"})

    def test_error_context_redacts_api_keys(self):
        """A-1: api_key values must not leak into PromptValidationError context."""
        config = {
            "prompt": "$missing_ref",
            "api_key": "sk-ant-secret-key-value-12345",
            "gemini_api_key": "AIzaSyActualGeminiKeyValue1234567890abc",
            "openai_api_key": "sk-openai-secret-99999",
            "name": "test_agent",
        }
        with patch(
            "agent_actions.prompt.formatter.PromptLoader.load_prompt",
            side_effect=FileNotFoundError("not found"),
        ):
            with pytest.raises(PromptValidationError) as exc_info:
                PromptFormatter.get_raw_prompt(config)
        ctx = exc_info.value.context["agent_config"]
        # Sensitive values must be redacted
        assert "sk-ant-secret-key-value-12345" not in ctx
        assert "AIzaSyActualGeminiKeyValue1234567890abc" not in ctx
        assert "sk-openai-secret-99999" not in ctx
        assert "[REDACTED]" in ctx
        # Non-sensitive values must survive
        assert "test_agent" in ctx
