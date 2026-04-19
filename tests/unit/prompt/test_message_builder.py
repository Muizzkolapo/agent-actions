"""String-equivalence and structural tests for MessageBuilder.

Each equivalence test verifies that ``MessageBuilder.build()`` produces the
**exact same** prompt text that the provider's original f-string + dedent()
generated, ensuring zero behavioural change during migration.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from textwrap import dedent

import pytest

from agent_actions.prompt.message_builder import (
    LLMMessage,
    LLMMessageEnvelope,
    MessageBuilder,
    _ensure_json_safe,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROMPT = "Analyse the sentiment of the following text."
CONTEXT_STR = "I love this product!"  # no braces to avoid StringProcessor escaping
SCHEMA_DICT = {"properties": {"sentiment": {"type": "string"}}, "type": "object"}


# ---------------------------------------------------------------------------
# Reference helpers — reproduce each provider's original f-string exactly
# ---------------------------------------------------------------------------


def _original_anthropic(prompt_config: str, context_data_str: str) -> str:
    """Reproduce Anthropic client.py _call_api line 143."""
    prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
    return dedent(prompt)


def _original_openai_json(prompt_config: str, context_data_str: str) -> str:
    """Reproduce OpenAI client.py call_json line 80."""
    prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            RULES: ALWAYS READ INPUT AS STRING\n        "
    return dedent(prompt)


def _original_openai_non_json(prompt_config: str, context_data_str: str) -> str:
    """Reproduce OpenAI client.py call_non_json line 201."""
    prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
    return dedent(prompt)


def _original_mistral_json(prompt_config: str, context_data_str: str, schema) -> str:
    """Reproduce Mistral client.py call_json line 87."""
    prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            <|begin_of_output_schema|> : {schema} : <|end_of_output_schema|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            "
    return dedent(prompt)


def _original_mistral_non_json(prompt_config: str, context_data_str: str) -> str:
    """Reproduce Mistral client.py call_non_json line 177."""
    prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            "
    return dedent(prompt)


def _original_gemini_json(prompt_config: str, context_data_str: str, schema) -> str:
    """Reproduce Gemini client.py call_json line 102."""
    prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n            <|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>\n\n            RULES: DO NOT ADD ANY KEY NOT IN PROVIDED SCHEMA LIST\n        "
    return dedent(prompt)


def _original_gemini_non_json(prompt_config: str, context_data_str: str) -> str:
    """Reproduce Gemini client.py call_non_json line 189."""
    prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
    return dedent(prompt)


def _original_groq_json(prompt_config: str, context_data_str: str) -> str:
    """Reproduce Groq client.py call_json line 78."""
    prompt = f"\n            <|begin_of_user_instruction|>:{prompt_config} :<|end_of_user_instruction|>\n\n            <|begin_of_text|>:: {context_data_str} :<|end_of_text|>\n        "
    return dedent(prompt)


def _original_groq_non_json(prompt_config: str, context_data_str: str) -> str:
    """Reproduce Groq client.py call_non_json line 170."""
    prompt = f"\n                Instructions: {prompt_config}\n                Input Text: {str(context_data_str)}\n                \n                Please provide a direct response without any JSON formatting.\n                Begin your response here:\n            "
    return dedent(prompt).strip()


def _original_cohere_json(
    prompt_config: str, context_data_str: str, schema_instruction: str
) -> str:
    """Reproduce Cohere client.py call_json line 115."""
    prompt = f"""\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            {schema_instruction}\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            """
    return dedent(prompt)


def _original_cohere_non_json(prompt_config: str, context_data_str: str) -> str:
    """Reproduce Cohere client.py call_non_json line 214."""
    prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
    return dedent(prompt)


# ---------------------------------------------------------------------------
# Tests — EXACT string equivalence (core safety guarantee)
# ---------------------------------------------------------------------------


class TestStringEquivalence:
    """Verify builder output is byte-identical to original f-string + dedent."""

    def test_anthropic_json(self):
        expected = _original_anthropic(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build(
            "anthropic", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        assert env.messages[0].content == expected

    def test_anthropic_non_json(self):
        expected = _original_anthropic(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build("anthropic", PROMPT, CONTEXT_STR, json_mode=False)
        assert env.messages[0].content == expected

    def test_openai_json(self):
        expected = _original_openai_json(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build("openai", PROMPT, CONTEXT_STR, json_mode=True)
        assert env.messages[0].content == expected

    def test_openai_non_json(self):
        expected = _original_openai_non_json(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build("openai", PROMPT, CONTEXT_STR, json_mode=False)
        assert env.messages[0].content == expected

    def test_mistral_json(self):
        expected = _original_mistral_json(PROMPT, CONTEXT_STR, SCHEMA_DICT)
        env = MessageBuilder.build(
            "mistral", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        assert env.messages[0].content == expected

    def test_mistral_non_json(self):
        expected = _original_mistral_non_json(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build("mistral", PROMPT, CONTEXT_STR, json_mode=False)
        assert env.messages[0].content == expected

    def test_gemini_json(self):
        expected = _original_gemini_json(PROMPT, CONTEXT_STR, SCHEMA_DICT)
        env = MessageBuilder.build(
            "gemini", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        assert env.prompt_body == expected

    def test_gemini_non_json(self):
        expected = _original_gemini_non_json(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build("gemini", PROMPT, CONTEXT_STR, json_mode=False)
        assert env.prompt_body == expected

    def test_groq_json(self):
        base = _original_groq_json(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=True)
        content = env.messages[0].content
        # Base Groq format is preserved; json rule is appended
        assert base.strip() in content
        assert "JSON" in content

    def test_groq_non_json(self):
        expected = _original_groq_non_json(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=False)
        assert env.messages[0].content == expected

    def test_cohere_json_with_schema(self):
        # Reproduce original schema_instruction for Cohere
        fields_str = ", ".join([f"'{f}'" for f in SCHEMA_DICT["properties"].keys()])
        schema_instruction = f"<|begin_of_output_schema|> : GENERATE JSON with the fields {fields_str} : <|end_of_output_schema|>"
        expected = _original_cohere_json(PROMPT, CONTEXT_STR, schema_instruction)
        env = MessageBuilder.build(
            "cohere", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        assert env.messages[0].content == expected

    def test_cohere_json_no_schema(self):
        schema_instruction = "<|begin_of_output_schema|> : GENERATE JSON : <|end_of_output_schema|>"
        expected = _original_cohere_json(PROMPT, CONTEXT_STR, schema_instruction)
        env = MessageBuilder.build("cohere", PROMPT, CONTEXT_STR, json_mode=True, schema=None)
        assert env.messages[0].content == expected

    def test_cohere_non_json(self):
        expected = _original_cohere_non_json(PROMPT, CONTEXT_STR)
        env = MessageBuilder.build("cohere", PROMPT, CONTEXT_STR, json_mode=False)
        assert env.messages[0].content == expected


# ---------------------------------------------------------------------------
# Tests — structural correctness
# ---------------------------------------------------------------------------


class TestMessageBuilderStructure:
    """Test that envelope structure is correct for each provider."""

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            MessageBuilder.build("nonexistent", PROMPT, CONTEXT_STR)

    def test_anthropic_json_single_user_message(self):
        env = MessageBuilder.build("anthropic", PROMPT, CONTEXT_STR, json_mode=True)
        assert len(env.messages) == 1
        assert env.messages[0].role == "user"

    def test_openai_json_system_message(self):
        env = MessageBuilder.build("openai", PROMPT, CONTEXT_STR, json_mode=True)
        assert len(env.messages) == 1
        assert env.messages[0].role == "system"

    def test_openai_non_json_user_message(self):
        env = MessageBuilder.build("openai", PROMPT, CONTEXT_STR, json_mode=False)
        assert len(env.messages) == 1
        assert env.messages[0].role == "user"

    def test_ollama_system_plus_user(self):
        env = MessageBuilder.build("ollama", PROMPT, CONTEXT_STR, json_mode=True)
        assert len(env.messages) == 2
        assert env.messages[0].role == "system"
        assert env.messages[1].role == "user"

    def test_groq_json_system_role(self):
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=True)
        assert len(env.messages) == 1
        assert env.messages[0].role == "system"

    def test_groq_non_json_system_role(self):
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=False)
        assert len(env.messages) == 1
        assert env.messages[0].role == "system"

    def test_batch_always_system_plus_user(self):
        env = MessageBuilder.build_for_batch("anthropic", PROMPT, CONTEXT_STR)
        assert len(env.messages) == 2
        assert env.messages[0] == LLMMessage(role="system", content=PROMPT)
        assert env.messages[1] == LLMMessage(role="user", content=CONTEXT_STR)


# ---------------------------------------------------------------------------
# Tests — content correctness (tagged providers)
# ---------------------------------------------------------------------------


class TestTaggedContent:
    """Verify tagged prompt bodies contain the expected markers."""

    @pytest.mark.parametrize("provider", ["anthropic", "openai", "mistral", "gemini", "cohere"])
    def test_tagged_providers_contain_instruction_tags(self, provider):
        env = MessageBuilder.build(
            provider, PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        content = env.messages[0].content
        assert "<|begin_of_user_instruction|>" in content
        assert "<|end_of_user_instruction|>" in content
        assert "<|begin_of_text|>" in content
        assert "<|end_of_text|>" in content

    def test_mistral_json_has_inline_schema(self):
        env = MessageBuilder.build(
            "mistral", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        content = env.messages[0].content
        assert "<|begin_of_output_schema|>" in content
        assert "<|end_of_output_schema|>" in content

    def test_gemini_json_has_inline_schema_with_list_wrapper(self):
        env = MessageBuilder.build(
            "gemini", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        content = env.messages[0].content
        assert "<|begin_of_output_schema|>" in content
        assert "list of this [" in content

    def test_mistral_json_no_list_wrapper(self):
        env = MessageBuilder.build(
            "mistral", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        content = env.messages[0].content
        assert "list of this" not in content

    def test_cohere_json_has_field_names_schema(self):
        env = MessageBuilder.build(
            "cohere", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        content = env.messages[0].content
        assert "GENERATE JSON with the fields" in content
        assert "'sentiment'" in content

    def test_cohere_json_no_schema(self):
        env = MessageBuilder.build("cohere", PROMPT, CONTEXT_STR, json_mode=True, schema=None)
        content = env.messages[0].content
        assert "GENERATE JSON" in content

    def test_openai_json_has_rules(self):
        env = MessageBuilder.build("openai", PROMPT, CONTEXT_STR, json_mode=True)
        content = env.messages[0].content
        assert "RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA" in content
        assert "RULES: ALWAYS READ INPUT AS STRING" in content

    def test_openai_non_json_no_rules(self):
        env = MessageBuilder.build("openai", PROMPT, CONTEXT_STR, json_mode=False)
        content = env.messages[0].content
        assert "RULES:" not in content

    def test_anthropic_no_rules(self):
        env = MessageBuilder.build(
            "anthropic", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        content = env.messages[0].content
        assert "RULES:" not in content

    def test_anthropic_no_inline_schema(self):
        env = MessageBuilder.build(
            "anthropic", PROMPT, CONTEXT_STR, json_mode=True, schema=SCHEMA_DICT
        )
        content = env.messages[0].content
        assert "<|begin_of_output_schema|>" not in content

    def test_mistral_json_no_schema_skips_schema_tag(self):
        env = MessageBuilder.build("mistral", PROMPT, CONTEXT_STR, json_mode=True, schema=None)
        content = env.messages[0].content
        assert "<|begin_of_output_schema|>" not in content

    def test_gemini_json_no_schema_skips_schema_tag(self):
        env = MessageBuilder.build("gemini", PROMPT, CONTEXT_STR, json_mode=True, schema=None)
        content = env.messages[0].content
        assert "<|begin_of_output_schema|>" not in content


# ---------------------------------------------------------------------------
# Tests — Groq format specifics
# ---------------------------------------------------------------------------


class TestGroqFormat:
    """Verify Groq's unique formats for json and non-json."""

    def test_groq_json_no_space_after_instruction_colon(self):
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=True)
        content = env.messages[0].content
        assert f"<|begin_of_user_instruction|>:{PROMPT}" in content

    def test_groq_json_double_colon_before_text(self):
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=True)
        content = env.messages[0].content
        assert f"<|begin_of_text|>:: {CONTEXT_STR}" in content

    def test_groq_json_blank_line_between_tags(self):
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=True)
        content = env.messages[0].content
        assert ":<|end_of_user_instruction|>\n\n<|begin_of_text|>" in content

    def test_groq_non_json_plain_text_format(self):
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=False)
        content = env.messages[0].content
        assert content.startswith("Instructions:")
        assert "Input Text:" in content
        assert "Please provide a direct response" in content
        assert "<|begin_of_user_instruction|>" not in content

    def test_groq_json_uses_tags(self):
        env = MessageBuilder.build("groq", PROMPT, CONTEXT_STR, json_mode=True)
        content = env.messages[0].content
        assert "<|begin_of_user_instruction|>" in content


# ---------------------------------------------------------------------------
# Tests — Ollama raw mode
# ---------------------------------------------------------------------------


class TestOllamaRaw:
    """Verify Ollama's system+user message structure."""

    def test_ollama_system_is_prompt(self):
        env = MessageBuilder.build("ollama", PROMPT, CONTEXT_STR, json_mode=True)
        assert env.messages[0].content == PROMPT

    def test_ollama_user_is_context(self):
        env = MessageBuilder.build("ollama", PROMPT, CONTEXT_STR, json_mode=True)
        assert env.messages[1].content == CONTEXT_STR

    def test_ollama_dict_context_serialised(self):
        ctx = {"text": "hello"}
        env = MessageBuilder.build("ollama", PROMPT, ctx, json_mode=True)
        assert env.messages[1].content == '{"text": "hello"}'

    def test_ollama_no_tags(self):
        env = MessageBuilder.build("ollama", PROMPT, CONTEXT_STR, json_mode=True)
        for msg in env.messages:
            assert "<|begin_of_user_instruction|>" not in msg.content


# ---------------------------------------------------------------------------
# Tests — non-json mode skips schema injection
# ---------------------------------------------------------------------------


class TestNonJsonSkipsSchema:
    """In non-json mode no provider should inject schema into the prompt."""

    @pytest.mark.parametrize(
        "provider", ["anthropic", "openai", "mistral", "gemini", "groq", "cohere", "ollama"]
    )
    def test_non_json_no_schema_tags(self, provider):
        env = MessageBuilder.build(
            provider, PROMPT, CONTEXT_STR, json_mode=False, schema=SCHEMA_DICT
        )
        for msg in env.messages:
            assert "<|begin_of_output_schema|>" not in msg.content


# ---------------------------------------------------------------------------
# Tests — batch builder
# ---------------------------------------------------------------------------


class TestBatchBuilder:
    """Verify batch message envelope construction."""

    def test_batch_envelope_structure(self):
        env = MessageBuilder.build_for_batch("anthropic", PROMPT, CONTEXT_STR)
        assert isinstance(env, LLMMessageEnvelope)
        assert len(env.messages) == 2
        assert env.messages[0] == LLMMessage(role="system", content=PROMPT)
        assert env.messages[1] == LLMMessage(role="user", content=CONTEXT_STR)

    def test_batch_prompt_body_is_prompt(self):
        env = MessageBuilder.build_for_batch("openai", PROMPT, CONTEXT_STR)
        assert env.prompt_body == PROMPT

    def test_batch_gemini_single_combined_message(self):
        env = MessageBuilder.build_for_batch("gemini", PROMPT, CONTEXT_STR)
        assert len(env.messages) == 1
        assert env.messages[0].role == "user"
        assert env.messages[0].content == f"{PROMPT}\n\n{CONTEXT_STR}"

    def test_batch_gemini_prompt_body(self):
        env = MessageBuilder.build_for_batch("gemini", PROMPT, CONTEXT_STR)
        assert env.prompt_body == PROMPT


# ---------------------------------------------------------------------------
# Tests — to_dicts() helper
# ---------------------------------------------------------------------------


class TestToDicts:
    """Verify LLMMessageEnvelope.to_dicts() helper."""

    def test_to_dicts_returns_all_messages(self):
        env = MessageBuilder.build("ollama", PROMPT, CONTEXT_STR, json_mode=True)
        dicts = env.to_dicts()
        assert len(dicts) == 2
        assert dicts[0] == {"role": "system", "content": PROMPT}
        assert dicts[1] == {"role": "user", "content": CONTEXT_STR}

    def test_to_dicts_filter_by_role(self):
        env = MessageBuilder.build_for_batch("anthropic", PROMPT, CONTEXT_STR)
        user_dicts = env.to_dicts(role="user")
        assert len(user_dicts) == 1
        assert user_dicts[0]["role"] == "user"
        system_dicts = env.to_dicts(role="system")
        assert len(system_dicts) == 1
        assert system_dicts[0]["content"] == PROMPT

    def test_to_dicts_single_message(self):
        env = MessageBuilder.build("anthropic", PROMPT, CONTEXT_STR, json_mode=True)
        dicts = env.to_dicts()
        assert len(dicts) == 1
        assert dicts[0]["role"] == "user"

    def test_to_dicts_filter_returns_empty_for_missing_role(self):
        env = MessageBuilder.build("anthropic", PROMPT, CONTEXT_STR, json_mode=True)
        dicts = env.to_dicts(role="system")
        assert dicts == []


# ---------------------------------------------------------------------------
# Tests — envelope metadata
# ---------------------------------------------------------------------------


class TestEnvelopeMetadata:
    """Verify rules and prompt_body are populated correctly."""

    def test_rules_populated_for_openai_json(self):
        env = MessageBuilder.build("openai", PROMPT, CONTEXT_STR, json_mode=True)
        assert len(env.rules) == 2

    def test_rules_empty_for_anthropic(self):
        env = MessageBuilder.build("anthropic", PROMPT, CONTEXT_STR, json_mode=True)
        assert env.rules == []

    def test_prompt_body_empty_for_ollama(self):
        env = MessageBuilder.build("ollama", PROMPT, CONTEXT_STR, json_mode=True)
        assert env.prompt_body == ""

    def test_prompt_body_non_empty_for_tagged(self):
        env = MessageBuilder.build("anthropic", PROMPT, CONTEXT_STR, json_mode=True)
        assert len(env.prompt_body) > 0


# ---------------------------------------------------------------------------
# Tests — edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge-case coverage for empty inputs and legacy schemas."""

    def test_empty_prompt(self):
        env = MessageBuilder.build("anthropic", "", CONTEXT_STR, json_mode=True)
        assert (
            "<|begin_of_user_instruction|>:  :<|end_of_user_instruction|>"
            in env.messages[0].content
        )

    def test_empty_context(self):
        env = MessageBuilder.build("anthropic", PROMPT, "", json_mode=True)
        assert "<|begin_of_text|>:  :<|end_of_text|>" in env.messages[0].content

    def test_cohere_legacy_dict_schema_without_properties(self):
        legacy_schema = {"name": {"type": "string"}, "age": {"type": "integer"}}
        env = MessageBuilder.build(
            "cohere", PROMPT, CONTEXT_STR, json_mode=True, schema=legacy_schema
        )
        content = env.messages[0].content
        assert "'name'" in content
        assert "'age'" in content

    def test_batch_empty_prompt_anthropic_style(self):
        """Anthropic batch should omit system message content for empty prompts."""
        env = MessageBuilder.build_for_batch("anthropic", "", CONTEXT_STR)
        system_dicts = env.to_dicts(role="system")
        # The envelope has a system message with empty content;
        # the Anthropic batch client checks truthiness before setting params["system"]
        assert system_dicts[0]["content"] == ""


# ---------------------------------------------------------------------------
# Tests — _ensure_json_safe utility
# ---------------------------------------------------------------------------


class TestEnsureJsonSafe:
    """Verify _ensure_json_safe converts non-serializable types correctly."""

    def test_primitives_pass_through(self):
        assert _ensure_json_safe(None) is None
        assert _ensure_json_safe(True) is True
        assert _ensure_json_safe(42) == 42
        assert _ensure_json_safe(3.14) == 3.14
        assert _ensure_json_safe("hello") == "hello"

    def test_nan_replaced_with_none(self):
        result = _ensure_json_safe(float("nan"))
        assert result is None

    def test_infinity_replaced_with_none(self):
        assert _ensure_json_safe(float("inf")) is None
        assert _ensure_json_safe(float("-inf")) is None

    def test_bytes_decoded_to_string(self):
        assert _ensure_json_safe(b"hello") == "hello"

    def test_bytes_with_invalid_utf8(self):
        result = _ensure_json_safe(b"\xff\xfe")
        assert isinstance(result, str)

    def test_set_converted_to_list(self):
        result = _ensure_json_safe({1, 2, 3})
        assert isinstance(result, list)
        assert sorted(result) == [1, 2, 3]

    def test_frozenset_converted_to_list(self):
        result = _ensure_json_safe(frozenset(["a", "b"]))
        assert isinstance(result, list)
        assert sorted(result) == ["a", "b"]

    def test_datetime_to_isoformat(self):
        dt = datetime(2026, 4, 19, 12, 0, 0)
        assert _ensure_json_safe(dt) == "2026-04-19T12:00:00"

    def test_date_to_isoformat(self):
        d = date(2026, 4, 19)
        assert _ensure_json_safe(d) == "2026-04-19"

    def test_tuple_converted_to_list(self):
        result = _ensure_json_safe((1, "a", True))
        assert result == [1, "a", True]

    def test_nested_dict_sanitised(self):
        data = {
            "name": "test",
            "score": float("nan"),
            "tags": {"a", "b"},
            "created": date(2026, 1, 1),
        }
        result = _ensure_json_safe(data)
        assert result["name"] == "test"
        assert result["score"] is None
        assert isinstance(result["tags"], list)
        assert result["created"] == "2026-01-01"
        # Entire result must be JSON-serializable
        json.dumps(result)  # Should not raise

    def test_nested_list_sanitised(self):
        data = [float("inf"), b"data", {1, 2}]
        result = _ensure_json_safe(data)
        assert result[0] is None
        assert result[1] == "data"
        assert isinstance(result[2], list)
        json.dumps(result)

    def test_custom_object_becomes_string(self):
        class Custom:
            def __repr__(self):
                return "Custom()"

        result = _ensure_json_safe(Custom())
        assert result == "Custom()"
        json.dumps(result)

    def test_deeply_nested_sanitisation(self):
        data = {"level1": {"level2": [{"value": float("nan"), "items": {1, 2}}]}}
        result = _ensure_json_safe(data)
        assert result["level1"]["level2"][0]["value"] is None
        assert isinstance(result["level1"]["level2"][0]["items"], list)
        json.dumps(result)

    def test_non_string_dict_keys_converted(self):
        data = {1: "one", 2: "two"}
        result = _ensure_json_safe(data)
        assert all(isinstance(k, str) for k in result.keys())
        assert result["1"] == "one"
        assert result["2"] == "two"
        json.dumps(result)


# ---------------------------------------------------------------------------
# Tests — context serialisation with non-serializable types
# ---------------------------------------------------------------------------


class TestContextSerialisationJsonSafety:
    """Verify _serialise_context handles dict context with non-serializable types."""

    def test_ollama_dict_with_nan_serialises(self):
        ctx = {"temperature": float("nan"), "text": "hello"}
        env = MessageBuilder.build("ollama", PROMPT, ctx, json_mode=True)
        content = env.messages[1].content
        parsed = json.loads(content)
        assert parsed["temperature"] is None
        assert parsed["text"] == "hello"

    def test_ollama_dict_with_datetime_serialises(self):
        ctx = {"created": datetime(2026, 4, 19), "text": "hello"}
        env = MessageBuilder.build("ollama", PROMPT, ctx, json_mode=True)
        content = env.messages[1].content
        parsed = json.loads(content)
        assert parsed["created"] == "2026-04-19T00:00:00"

    def test_ollama_dict_with_bytes_serialises(self):
        ctx = {"data": b"binary", "text": "hello"}
        env = MessageBuilder.build("ollama", PROMPT, ctx, json_mode=True)
        content = env.messages[1].content
        parsed = json.loads(content)
        assert parsed["data"] == "binary"

    def test_openai_dict_context_with_nan_produces_valid_string(self):
        ctx = {"score": float("nan"), "text": "hello"}
        env = MessageBuilder.build("openai", PROMPT, ctx, json_mode=True)
        content = env.messages[0].content
        assert "None" in content  # NaN replaced with None before str()
        assert isinstance(content, str)

    def test_openai_dict_context_with_set_produces_valid_string(self):
        ctx = {"tags": {"a", "b"}, "text": "hello"}
        env = MessageBuilder.build("openai", PROMPT, ctx, json_mode=True)
        content = env.messages[0].content
        assert isinstance(content, str)
