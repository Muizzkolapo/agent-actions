"""Unified message builder for LLM provider prompt assembly.

Centralises the f-string prompt wrapping that was previously duplicated
across every provider client.  Each provider declares its preferences via
a frozen ``ProviderMessageConfig``; the ``MessageBuilder`` reads the config
and produces a provider-agnostic ``LLMMessageEnvelope`` that the provider
converts to its SDK-specific format in the last mile.

Architecture invariant: all prompt-to-message assembly MUST go through
``MessageBuilder.build()`` so that formatting changes are made in one place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from textwrap import dedent
from typing import Any

from agent_actions.input.preprocessing.transformation.string_transformer import (
    StringProcessor,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PromptStyle(Enum):
    """How the instruction + context body is formatted."""

    TAGGED = "tagged"
    """Standard ``<|begin_of_user_instruction|>`` / ``<|begin_of_text|>`` tags."""

    TAGGED_GROQ = "tagged_groq"
    """Groq JSON variant: no space after first colon, double colon before
    text, blank line between instruction and text tags."""

    PLAIN_TEXT = "plain_text"
    """Groq non-json style: ``Instructions: ... / Input Text: ...``."""

    RAW = "raw"
    """No wrapping — prompt and context are used as-is (Ollama)."""


class SchemaInjection(Enum):
    """Whether and how the schema is injected into the prompt text."""

    NONE = "none"
    """Schema is NOT in the prompt — provider passes it via API parameter."""

    INLINE_FULL = "inline_full"
    """Full schema repr injected with ``<|begin_of_output_schema|>`` tags (Mistral)."""

    INLINE_FULL_LIST = "inline_full_list"
    """Schema wrapped as ``list of this [...]`` (Gemini)."""

    INLINE_FIELDS = "inline_fields"
    """Only field names injected (Cohere style)."""


class MessageRole(Enum):
    """How messages are structured for the provider."""

    SINGLE_USER = "single_user"
    """One message with role='user' containing the full body."""

    SYSTEM_PLUS_USER = "system_user"
    """System message = prompt, user message = context (Ollama)."""

    SYSTEM_ONLY = "system_only"
    """One message with role='system' containing the full body."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMMessage:
    """A single message in a chat conversation."""

    role: str
    content: str


@dataclass
class LLMMessageEnvelope:
    """Complete set of messages ready for a provider, plus metadata."""

    messages: list[LLMMessage]
    prompt_body: str = ""
    """The assembled prompt text *before* role wrapping.  Gemini online uses
    this directly; all other providers use ``messages``.  Empty for Ollama
    (RAW style)."""
    rules: list[str] = field(default_factory=list)

    def to_dicts(self, *, role: str | None = None) -> list[dict[str, str]]:
        """Convert messages to plain dicts for provider SDKs.

        Args:
            role: If set, only include messages with this role.
        """
        msgs = self.messages if role is None else [m for m in self.messages if m.role == role]
        return [{"role": m.role, "content": m.content} for m in msgs]


# ---------------------------------------------------------------------------
# Provider configuration registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderMessageConfig:
    """Declares how a provider wants its messages constructed."""

    json_prompt_style: PromptStyle
    non_json_prompt_style: PromptStyle
    json_role: MessageRole
    non_json_role: MessageRole
    schema_injection: SchemaInjection
    json_rules: tuple[str, ...] = ()
    non_json_rules: tuple[str, ...] = ()
    blank_line_before_rules: bool = True
    """Whether to insert a blank line before RULES text.  Most providers
    had ``\\n\\n`` before RULES in their original f-strings; Cohere did not."""


PROVIDER_MESSAGE_CONFIGS: dict[str, ProviderMessageConfig] = {
    "anthropic": ProviderMessageConfig(
        json_prompt_style=PromptStyle.TAGGED,
        non_json_prompt_style=PromptStyle.TAGGED,
        json_role=MessageRole.SINGLE_USER,
        non_json_role=MessageRole.SINGLE_USER,
        schema_injection=SchemaInjection.NONE,
    ),
    "openai": ProviderMessageConfig(
        json_prompt_style=PromptStyle.TAGGED,
        non_json_prompt_style=PromptStyle.TAGGED,
        json_role=MessageRole.SYSTEM_ONLY,
        non_json_role=MessageRole.SINGLE_USER,
        schema_injection=SchemaInjection.NONE,
        json_rules=(
            "RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT",
            "RULES: ALWAYS READ INPUT AS STRING",
        ),
    ),
    "mistral": ProviderMessageConfig(
        json_prompt_style=PromptStyle.TAGGED,
        non_json_prompt_style=PromptStyle.TAGGED,
        json_role=MessageRole.SINGLE_USER,
        non_json_role=MessageRole.SINGLE_USER,
        schema_injection=SchemaInjection.INLINE_FULL,
        json_rules=("RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT",),
    ),
    "gemini": ProviderMessageConfig(
        json_prompt_style=PromptStyle.TAGGED,
        non_json_prompt_style=PromptStyle.TAGGED,
        json_role=MessageRole.SINGLE_USER,
        non_json_role=MessageRole.SINGLE_USER,
        schema_injection=SchemaInjection.INLINE_FULL_LIST,
        json_rules=("RULES: DO NOT ADD ANY KEY NOT IN PROVIDED SCHEMA LIST",),
    ),
    "groq": ProviderMessageConfig(
        json_prompt_style=PromptStyle.TAGGED_GROQ,
        non_json_prompt_style=PromptStyle.PLAIN_TEXT,
        json_role=MessageRole.SYSTEM_ONLY,
        non_json_role=MessageRole.SYSTEM_ONLY,
        schema_injection=SchemaInjection.NONE,
    ),
    "cohere": ProviderMessageConfig(
        json_prompt_style=PromptStyle.TAGGED,
        non_json_prompt_style=PromptStyle.TAGGED,
        json_role=MessageRole.SINGLE_USER,
        non_json_role=MessageRole.SINGLE_USER,
        schema_injection=SchemaInjection.INLINE_FIELDS,
        json_rules=("RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT",),
        blank_line_before_rules=False,
    ),
    "ollama": ProviderMessageConfig(
        json_prompt_style=PromptStyle.RAW,
        non_json_prompt_style=PromptStyle.RAW,
        json_role=MessageRole.SYSTEM_PLUS_USER,
        non_json_role=MessageRole.SYSTEM_PLUS_USER,
        schema_injection=SchemaInjection.NONE,
    ),
}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class MessageBuilder:
    """Builds provider-ready ``LLMMessageEnvelope`` from prompt + context.

    Single source of truth for the f-string assembly that was previously
    duplicated across all provider clients.
    """

    # -- public API ----------------------------------------------------------

    @staticmethod
    def build(
        provider: str,
        prompt_config: str,
        context_data: str | dict[str, Any],
        *,
        schema: dict[str, Any] | None = None,
        json_mode: bool = True,
    ) -> LLMMessageEnvelope:
        """Build a message envelope for a realtime (online) provider call."""
        config = MessageBuilder._get_config(provider)
        style = config.json_prompt_style if json_mode else config.non_json_prompt_style
        role = config.json_role if json_mode else config.non_json_role
        rules_tuple = config.json_rules if json_mode else config.non_json_rules

        context_str = MessageBuilder._serialise_context(context_data, provider)
        rules = list(rules_tuple)

        body = MessageBuilder._assemble_body(
            style=style,
            prompt_config=prompt_config,
            context_str=context_str,
            schema=schema,
            schema_injection=config.schema_injection if json_mode else SchemaInjection.NONE,
            rules=rules,
            blank_line_before_rules=config.blank_line_before_rules,
        )

        messages = MessageBuilder._wrap_in_roles(role, prompt_config, context_str, body)

        return LLMMessageEnvelope(
            messages=messages,
            prompt_body=body,
            rules=rules,
        )

    @staticmethod
    def build_for_batch(
        provider: str,
        prompt: str,
        user_content: str,
        *,
        schema: dict[str, Any] | None = None,
    ) -> LLMMessageEnvelope:
        """Build a message envelope for a batch provider call.

        Most providers use system + user messages.  Anthropic uses a
        separate ``system`` param plus a single user message.  Gemini
        combines prompt and content into one text string.
        """
        if provider == "gemini":
            # Gemini batch: single combined text
            combined = f"{prompt}\n\n{user_content}"
            messages = [LLMMessage(role="user", content=combined)]
        else:
            # Standard (including Anthropic): system + user messages.
            # Anthropic batch consumers split system out as a top-level param.
            messages = [
                LLMMessage(role="system", content=prompt),
                LLMMessage(role="user", content=user_content),
            ]
        return LLMMessageEnvelope(
            messages=messages,
            prompt_body=prompt,
        )

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _get_config(provider: str) -> ProviderMessageConfig:
        """Look up provider config, raising on unknown provider."""
        config = PROVIDER_MESSAGE_CONFIGS.get(provider)
        if config is None:
            raise ValueError(
                f"Unknown provider '{provider}'. Known: {sorted(PROVIDER_MESSAGE_CONFIGS.keys())}"
            )
        return config

    @staticmethod
    def _serialise_context(
        context_data: str | dict[str, Any],
        provider: str,
    ) -> str:
        """Convert context_data to a string for prompt embedding."""
        if provider == "ollama":
            # Ollama handles its own serialisation (json.dumps)
            import json

            if isinstance(context_data, str):
                return context_data
            return json.dumps(context_data, ensure_ascii=False)

        return StringProcessor.process_as_string(context_data)

    @staticmethod
    def _assemble_body(
        *,
        style: PromptStyle,
        prompt_config: str,
        context_str: str,
        schema: dict[str, Any] | None,
        schema_injection: SchemaInjection,
        rules: list[str],
        blank_line_before_rules: bool = True,
    ) -> str:
        """Assemble the prompt body text from parts.

        TAGGED and TAGGED_GROQ outputs are wrapped with leading/trailing
        newlines to match the original ``dedent()`` output format.
        """
        if style == PromptStyle.RAW:
            # Ollama: no body assembly — roles handle it
            return ""

        if style == PromptStyle.PLAIN_TEXT:
            # Groq non-json — strip() matches original dedent().strip()
            body = dedent(f"""\
                Instructions: {prompt_config}
                Input Text: {str(context_str)}

                Please provide a direct response without any JSON formatting.
                Begin your response here:""").strip()
            return body

        if style == PromptStyle.TAGGED_GROQ:
            # Groq JSON — unique format: no space after first colon,
            # double colon before text, blank line between tags
            parts: list[str] = [
                f"<|begin_of_user_instruction|>:{prompt_config} :<|end_of_user_instruction|>",
                "",  # blank line between tags
                f"<|begin_of_text|>:: {context_str} :<|end_of_text|>",
            ]
            joined = "\n".join(parts)
            return f"\n{joined}\n"

        # -- TAGGED style (default for most providers) -----------------------
        parts = [
            f"<|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>",
            f"<|begin_of_text|>: {str(context_str)} :<|end_of_text|>",
        ]

        # Schema injection (only in json mode)
        if schema_injection == SchemaInjection.INLINE_FULL and schema is not None:
            parts.append(f"<|begin_of_output_schema|> : {schema} : <|end_of_output_schema|>")
        elif schema_injection == SchemaInjection.INLINE_FULL_LIST and schema is not None:
            parts.append(
                f"<|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>"
            )
        elif schema_injection == SchemaInjection.INLINE_FIELDS:
            parts.append(MessageBuilder._build_field_schema_instruction(schema))

        # Rules
        if rules:
            if blank_line_before_rules:
                parts.append("")  # blank line before rules (OpenAI, Mistral, Gemini)
            parts.extend(rules)

        # Wrap with \n...\n to match original dedent() output
        joined = "\n".join(parts)
        return f"\n{joined}\n"

    @staticmethod
    def _build_field_schema_instruction(schema: dict[str, Any] | None) -> str:
        """Build Cohere-style schema instruction from field names."""
        if schema is None:
            return "<|begin_of_output_schema|> : GENERATE JSON : <|end_of_output_schema|>"

        if "properties" in schema:
            schema_fields = schema["properties"].keys()
        else:
            schema_fields = schema.keys()

        fields_str = ", ".join([f"'{fname}'" for fname in schema_fields])
        return f"<|begin_of_output_schema|> : GENERATE JSON with the fields {fields_str} : <|end_of_output_schema|>"

    @staticmethod
    def _wrap_in_roles(
        role: MessageRole,
        prompt_config: str,
        context_str: str,
        body: str,
    ) -> list[LLMMessage]:
        """Wrap the assembled body into the correct message role structure."""
        if role == MessageRole.SYSTEM_PLUS_USER:
            # Ollama: system=prompt, user=context
            return [
                LLMMessage(role="system", content=prompt_config),
                LLMMessage(role="user", content=context_str),
            ]

        if role == MessageRole.SYSTEM_ONLY:
            return [LLMMessage(role="system", content=body)]

        # SINGLE_USER (default)
        return [LLMMessage(role="user", content=body)]
