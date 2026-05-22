"""Tests for MessageBuilder token overflow guard and prompt injection fix."""

from __future__ import annotations

import pytest

from agent_actions.errors import PromptTooLargeError
from agent_actions.prompt.message_builder import (
    MessageBuilder,
)

# ---------------------------------------------------------------------------
# Defect 1: Token overflow pre-flight guard
# ---------------------------------------------------------------------------


class TestTokenOverflowGuard:
    """Token estimation guard rejects oversized prompts before API call."""

    def test_oversized_prompt_raises_prompt_too_large_error(self):
        """A 500K-char prompt exceeds gpt-4's 8K context and raises."""
        giant_prompt = "x" * 500_000
        with pytest.raises(PromptTooLargeError, match="exceeds model context window"):
            MessageBuilder.build(
                "openai",
                giant_prompt,
                "context",
                json_mode=True,
                model_name="gpt-4",
            )

    def test_small_prompt_passes_guard(self):
        """A small prompt fits within context window and succeeds."""
        envelope = MessageBuilder.build(
            "openai",
            "Analyse sentiment.",
            "I love this!",
            json_mode=True,
            model_name="gpt-4",
        )
        assert len(envelope.messages) > 0

    def test_no_model_name_skips_guard(self):
        """When model_name is None (default), no token check runs."""
        giant_prompt = "x" * 500_000
        # Should not raise — guard is skipped when model_name is None
        envelope = MessageBuilder.build(
            "openai",
            giant_prompt,
            "context",
            json_mode=True,
        )
        assert len(envelope.messages) > 0

    def test_unknown_model_uses_default_limit(self):
        """Unknown model names use _DEFAULT_CONTEXT_LIMIT (128K)."""
        # 128K * 4 = 512K chars needed to exceed default limit
        prompt = "x" * 600_000
        with pytest.raises(PromptTooLargeError):
            MessageBuilder.build(
                "openai",
                prompt,
                "ctx",
                json_mode=True,
                model_name="unknown-model-xyz",
            )

    def test_error_context_includes_token_info(self):
        """PromptTooLargeError includes estimated_tokens and model_limit."""
        giant_prompt = "x" * 500_000
        with pytest.raises(PromptTooLargeError) as exc_info:
            MessageBuilder.build(
                "openai",
                giant_prompt,
                "ctx",
                json_mode=True,
                model_name="gpt-4",
            )
        assert exc_info.value.context["model_limit"] == 8_192
        assert exc_info.value.context["estimated_tokens"] > 8_192

    def test_anthropic_model_limit_used(self):
        """Anthropic model limits are recognized."""
        # Claude models have 200K limit; prompt under that should pass
        envelope = MessageBuilder.build(
            "anthropic",
            "Analyse sentiment.",
            "I love this!",
            json_mode=True,
            model_name="claude-3-opus-20240229",
        )
        assert len(envelope.messages) > 0


# ---------------------------------------------------------------------------
# Defect 2: OpenAI JSON mode prompt injection fix
# ---------------------------------------------------------------------------


class TestOpenAIPromptInjectionFix:
    """User data goes in user message, not system message, for OpenAI JSON mode."""

    def test_openai_json_mode_splits_system_and_user(self):
        """OpenAI JSON mode puts instructions in system, context in user."""
        envelope = MessageBuilder.build(
            "openai",
            "Extract entities from:",
            "USER INJECTED DATA",
            json_mode=True,
        )
        messages = envelope.to_dicts()
        system_msgs = [m for m in messages if m["role"] == "system"]
        user_msgs = [m for m in messages if m["role"] == "user"]

        # User data must NOT be in system message
        for m in system_msgs:
            content = m["content"] if isinstance(m["content"], str) else m["content"][0]["text"]
            assert "USER INJECTED DATA" not in content

        # User data must be in user message
        assert any("USER INJECTED DATA" in m["content"] for m in user_msgs)

    def test_openai_json_mode_has_two_messages(self):
        """OpenAI JSON mode produces system + user messages."""
        envelope = MessageBuilder.build(
            "openai",
            "instructions",
            "context data",
            json_mode=True,
        )
        messages = envelope.to_dicts()
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_openai_non_json_unchanged(self):
        """OpenAI non-JSON mode (SINGLE_USER) is unaffected."""
        envelope = MessageBuilder.build(
            "openai",
            "instructions",
            "context data",
            json_mode=False,
        )
        messages = envelope.to_dicts()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_groq_json_mode_still_single_system(self):
        """Groq JSON mode (TAGGED_GROQ style) keeps single system message."""
        envelope = MessageBuilder.build(
            "groq",
            "instructions",
            "context data",
            json_mode=True,
        )
        messages = envelope.to_dicts()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    def test_groq_non_json_still_single_system(self):
        """Groq non-JSON mode keeps single system message."""
        envelope = MessageBuilder.build(
            "groq",
            "instructions",
            "context data",
            json_mode=False,
        )
        messages = envelope.to_dicts()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    def test_anthropic_unaffected(self):
        """Anthropic (SINGLE_USER) is unaffected by the split."""
        envelope = MessageBuilder.build(
            "anthropic",
            "instructions",
            "context data",
            json_mode=True,
        )
        messages = envelope.to_dicts()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_openai_json_mode_empty_context_single_system(self):
        """OpenAI JSON mode with empty context keeps single system message."""
        envelope = MessageBuilder.build(
            "openai",
            "instructions",
            "",
            json_mode=True,
        )
        messages = envelope.to_dicts()
        # Empty context_str → no split, body goes in system
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
