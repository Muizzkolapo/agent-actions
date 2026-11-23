"""Unified message builder for LLM provider prompt assembly.

Centralises the f-string prompt wrapping that was previously duplicated
across every provider client.  Each provider declares its preferences via
a frozen ``ProviderMessageConfig``; the ``MessageBuilder`` reads the config
and produces a provider-agnostic ``LLMMessageEnvelope`` that the provider
converts to its SDK-specific format in the last mile.

Architecture invariant: all prompt-to-message assembly MUST go through
``MessageBuilder.build()``, online and in batch, so that a batch line asks the
model what the online request asks and formatting changes are made in one place.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from textwrap import dedent
from typing import Any

from agent_actions.errors import PromptTooLargeError
from agent_actions.utils import deep_json
from agent_actions.utils.json_safety import ensure_json_safe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token estimation limits (chars / 4 heuristic — within ~20% of actual)
# ---------------------------------------------------------------------------

_DEFAULT_CONTEXT_LIMIT = 128_000

_OPENING = "<|begin_of_user_instruction|>: "
_GROQ_OPENING = "<|begin_of_user_instruction|>:"

_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # OpenAI
    "gpt-4": 8_192,
    "gpt-4-32k": 32_768,
    "gpt-4-turbo": 128_000,
    "gpt-4-turbo-preview": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4.1-nano": 1_047_576,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o1-pro": 200_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
    # Anthropic, as its model overview documents them
    "claude-3-haiku-20240307": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-opus-4-6": 1_000_000,
    "claude-opus-4-7": 1_000_000,
    "claude-opus-4-8": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-opus-5-5": 1_000_000,
    "claude-sonnet-4-6": 1_000_000,
    "claude-sonnet-5": 1_000_000,
    "claude-sonnet-5-5": 1_000_000,
    "claude-haiku-5-5": 1_000_000,
    "claude-fable-5": 1_000_000,
    "claude-fable-5-1": 1_000_000,
    "claude-fable-5-2": 1_000_000,
    "claude-mythos-5": 1_000_000,
    "claude-mythos-5-1": 1_000_000,
    "claude-mythos-5-2": 1_000_000,
    # Groq
    "llama-3.3-70b-versatile": 128_000,
    "llama-3.1-8b-instant": 128_000,
    "mixtral-8x7b-32768": 32_768,
    "gemma2-9b-it": 8_192,
}


def _context_limit(model_name: str | None, context_window: int | None) -> int:
    if context_window is not None:
        return context_window
    if model_name is None:
        return _DEFAULT_CONTEXT_LIMIT
    return _MODEL_CONTEXT_LIMITS.get(model_name, _DEFAULT_CONTEXT_LIMIT)


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
    """Full schema repr injected with ``<|begin_of_output_schema|>`` tags."""

    INLINE_FULL_LIST = "inline_full_list"
    """Schema wrapped as ``list of this [...]`` (Gemini)."""

    INLINE_FIELDS = "inline_fields"
    """Only field names injected (Cohere style)."""

    PROMPT = "prompt"
    """Schema injected into the prompt text for providers without native
    structured output support (e.g., Ollama Cloud)."""


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
    static_len: int = 0
    """Length of the leading prompt text, before any record content."""
    cache_boundaries: tuple[int, ...] = ()
    """Lengths of leading content, ascending, that other requests begin with too. A
    vendor with cache marks puts one at each; any other sends the content."""

    def __post_init__(self) -> None:
        if not 0 <= self.static_len <= len(self.content):
            raise ValueError(
                f"static_len {self.static_len} is outside a content of length {len(self.content)}"
            )
        ends = (0, *self.cache_boundaries)
        if any(a >= b for a, b in zip(ends, ends[1:], strict=False)) or ends[-1] > self.static_len:
            raise ValueError(
                f"Cache boundaries {self.cache_boundaries} must ascend within the prompt text, "
                f"whose length is {self.static_len}"
            )

    def segments(self) -> list[tuple[str, bool]]:
        """The content in order, as (text, whether a cache boundary ends it) pairs."""
        parts = []
        start = 0
        for end in self.cache_boundaries:
            parts.append((self.content[start:end], True))
            start = end
        if start < len(self.content) or not parts:
            parts.append((self.content[start:], False))
        return parts


@dataclass
class LLMMessageEnvelope:
    """Complete set of messages ready for a provider, plus metadata."""

    messages: list[LLMMessage]
    prompt_body: str = ""
    """The assembled prompt text *before* role wrapping.  Gemini sends this
    as its one text part; all other providers use ``messages``.  Empty for
    Ollama (RAW style)."""
    rules: list[str] = field(default_factory=list)

    def to_dicts(self, *, role: str | None = None) -> list[dict[str, Any]]:
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
        json_rules=("RULES: Respond in valid JSON format.",),
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
    "ollama_local": ProviderMessageConfig(
        json_prompt_style=PromptStyle.RAW,
        non_json_prompt_style=PromptStyle.RAW,
        json_role=MessageRole.SYSTEM_PLUS_USER,
        non_json_role=MessageRole.SYSTEM_PLUS_USER,
        schema_injection=SchemaInjection.NONE,
    ),
    "ollama_cloud": ProviderMessageConfig(
        json_prompt_style=PromptStyle.RAW,
        non_json_prompt_style=PromptStyle.RAW,
        json_role=MessageRole.SYSTEM_PLUS_USER,
        non_json_role=MessageRole.SYSTEM_PLUS_USER,
        # Cloud does not support structured outputs via format param yet.
        # Change to SchemaInjection.NONE when Ollama Cloud adds support.
        # See: https://github.com/ollama/ollama/issues/12362
        schema_injection=SchemaInjection.PROMPT,
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
        enable_prompt_caching: bool = False,
        shared_prompt_len: int | None = None,
        model_name: str | None = None,
        cache_points: Sequence[int] = (),
        context_window: int | None = None,
    ) -> LLMMessageEnvelope:
        """Build the message envelope of one provider request, online or a batch line.

        ``shared_prompt_len`` is the length of the leading part of ``prompt_config`` every
        record is sent; None means all of it. ``enable_prompt_caching`` puts a cache
        boundary at its end. ``cache_points`` are lengths of leading ``prompt_config``
        the template marked as shared by some records; each is a cache boundary.
        ``context_window`` is the action's setting; it outranks the model table.
        """
        MessageBuilder._check_shared_len(shared_prompt_len, prompt_config)
        MessageBuilder._check_cache_points(
            cache_points, _shared_len(prompt_config, shared_prompt_len)
        )
        config = MessageBuilder._get_config(provider)
        style = config.json_prompt_style if json_mode else config.non_json_prompt_style
        role = config.json_role if json_mode else config.non_json_role
        rules_tuple = config.json_rules if json_mode else config.non_json_rules

        context_str = MessageBuilder._serialise_context(context_data)
        rules = list(rules_tuple)

        schema_injection = config.schema_injection if json_mode else SchemaInjection.NONE

        body, body_static_len = MessageBuilder._assemble_body(
            style=style,
            prompt_config=prompt_config,
            context_str=context_str,
            schema=schema,
            schema_injection=schema_injection,
            rules=rules,
            blank_line_before_rules=config.blank_line_before_rules,
            shared_prompt_len=shared_prompt_len,
        )

        # SchemaInjection.PROMPT: inject schema into the prompt text so it
        # lands in the system message for providers that use RAW style
        # (no body assembly). Used by ollama_cloud until native structured
        # output support ships (ollama/ollama#12362).
        effective_prompt = prompt_config
        if schema_injection == SchemaInjection.PROMPT and schema is not None:
            clean_schema = MessageBuilder._strip_schema_metadata(schema)
            schema_text = json.dumps(clean_schema, indent=2, ensure_ascii=False)
            effective_prompt = (
                f"{prompt_config}\n\n"
                f"You MUST respond with valid JSON matching this schema:\n"
                f"{schema_text}\n\n"
                f"Return ONLY the JSON object, no extra text."
            )

        messages = MessageBuilder._wrap_in_roles(
            role,
            effective_prompt,
            context_str,
            body,
            body_static_len,
            style=style,
            shared_prompt_len=shared_prompt_len,
        )

        if enable_prompt_caching or cache_points:
            messages = MessageBuilder._place_cache_boundaries(
                messages,
                cache_points,
                _shared_len(prompt_config, shared_prompt_len),
                at_prompt_end=enable_prompt_caching,
            )

        estimated_tokens = sum(len(m.content) for m in messages) // 4
        model_limit = _context_limit(model_name, context_window)
        if estimated_tokens > model_limit:
            raise PromptTooLargeError(
                f"Estimated prompt size ({estimated_tokens} tokens) exceeds "
                f"model context window ({model_limit} tokens). If the model reads more, "
                "set context_window on the action or in defaults",
                context={
                    "estimated_tokens": estimated_tokens,
                    "model_limit": model_limit,
                    "provider": provider,
                    "model_name": model_name,
                },
            )

        return LLMMessageEnvelope(
            messages=messages,
            prompt_body=body,
            rules=rules,
        )

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _check_shared_len(shared_prompt_len: int | None, prompt: str) -> None:
        if shared_prompt_len is not None and not 0 <= shared_prompt_len <= len(prompt):
            raise ValueError(
                f"shared_prompt_len {shared_prompt_len} is outside a prompt of length "
                f"{len(prompt)}"
            )

    @staticmethod
    def _check_cache_points(cache_points: Sequence[int], shared_len: int) -> None:
        ends = (0, *cache_points)
        if any(a > b for a, b in zip(ends, ends[1:], strict=False)) or ends[-1] > shared_len:
            raise ValueError(
                f"Cache points {tuple(cache_points)} must ascend within the shared prompt, "
                f"whose length is {shared_len}"
            )

    @staticmethod
    def _place_cache_boundaries(
        messages: list[LLMMessage],
        cache_points: Sequence[int],
        shared_len: int,
        *,
        at_prompt_end: bool,
    ) -> list[LLMMessage]:
        """Put a cache boundary at each cache point and, asked to, at the end of the prompt text.

        Record content is never behind a boundary. A caller asks for the one at the end
        only when the prompt is the same for every record: a mark on text that changes
        per record writes a cache entry no other request reads. No boundary is placed
        where a text block it splits off would be blank, a block the API refuses.
        """
        last_shared: int | None = None
        for index, message in enumerate(messages):
            if message.static_len:
                last_shared = index
            if message.static_len < len(message.content):
                break
        if last_shared is None:
            return messages
        message = messages[last_shared]
        prompt_start = message.static_len - shared_len
        wanted = [prompt_start + point for point in cache_points]
        if at_prompt_end:
            wanted.append(message.static_len)
        boundaries: list[int] = []
        for end in wanted:
            if message.content[boundaries[-1] if boundaries else 0 : end].strip():
                boundaries.append(end)
        tail = message.content[boundaries[-1] :] if boundaries else ""
        if tail and not tail.strip():
            boundaries.pop()
        if not boundaries:
            return messages
        placed = list(messages)
        placed[last_shared] = replace(message, cache_boundaries=tuple(boundaries))
        return placed

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
    def _serialise_context(context_data: str | dict[str, Any]) -> str:
        """The context as the prompt embeds it: a string as written, a dict as JSON."""
        if isinstance(context_data, str):
            return context_data
        return deep_json.dumps(ensure_json_safe(context_data), ensure_ascii=False)

    _SCHEMA_META_KEYS = frozenset({"name", "title", "description"})

    @staticmethod
    def _strip_schema_metadata(schema: Any) -> Any:
        """Remove framework metadata keys before injecting schema into prompts.

        Keys like ``name``, ``title``, and ``description`` are framework
        labels (e.g. "InlineSchema") that leak implementation details into
        LLM context and can trigger schema-echo behavior where the model
        returns the schema definition itself instead of conforming data.
        """
        meta_keys = MessageBuilder._SCHEMA_META_KEYS
        if isinstance(schema, dict):
            stripped = {k: v for k, v in schema.items() if k not in meta_keys}
            # Also strip from nested schema wrappers (OpenAI: {"name":..., "schema": {...}})
            if "schema" in stripped and isinstance(stripped["schema"], dict):
                stripped["schema"] = {
                    k: v for k, v in stripped["schema"].items() if k not in meta_keys
                }
            if "input_schema" in stripped and isinstance(stripped["input_schema"], dict):
                stripped["input_schema"] = {
                    k: v for k, v in stripped["input_schema"].items() if k not in meta_keys
                }
            return stripped
        if isinstance(schema, list):
            return [MessageBuilder._strip_schema_metadata(item) for item in schema]
        return schema

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
        shared_prompt_len: int | None = None,
    ) -> tuple[str, int]:
        """Assemble the prompt body and the length of its text up to the end of the shared prompt.

        TAGGED and TAGGED_GROQ outputs are wrapped with leading/trailing
        newlines to match the original ``dedent()`` output format.
        """
        if style == PromptStyle.RAW:
            # Ollama: no body assembly — roles handle it
            return "", 0

        if style == PromptStyle.PLAIN_TEXT:
            # Groq non-json — strip() matches original dedent().strip()
            body = dedent(f"""\
                Instructions: {prompt_config}
                Input Text: {context_str!s}

                Please provide a direct response without any JSON formatting.
                Begin your response here:""").strip()
            return body, 0

        if style == PromptStyle.TAGGED_GROQ:
            # Groq JSON — unique format: no space after first colon,
            # double colon before text, blank line between tags
            parts: list[str] = [
                f"{_GROQ_OPENING}{prompt_config} :<|end_of_user_instruction|>",
                "",  # blank line between tags
                f"<|begin_of_text|>:: {context_str} :<|end_of_text|>",
            ]
            if rules:
                parts.append("")
                parts.extend(rules)
            joined = "\n".join(parts)
            return f"\n{joined}\n", 1 + len(_GROQ_OPENING) + _shared_len(
                prompt_config, shared_prompt_len
            )

        # -- TAGGED style (default for most providers) -----------------------
        parts = [
            f"{_OPENING}{prompt_config} :<|end_of_user_instruction|>",
            f"<|begin_of_text|>: {context_str!s} :<|end_of_text|>",
        ]

        schema_text = MessageBuilder._inline_schema_text(schema_injection, schema)
        if schema_text is not None:
            parts.append(schema_text)

        # Rules
        if rules:
            if blank_line_before_rules:
                parts.append("")  # blank line before rules (OpenAI, Gemini)
            parts.extend(rules)

        # Wrap with \n...\n to match original dedent() output. The shared text ends with the
        # prompt, before the closing tag: a repair call's feedback goes between the two.
        joined = "\n".join(parts)
        return f"\n{joined}\n", 1 + len(_OPENING) + _shared_len(prompt_config, shared_prompt_len)

    @staticmethod
    def _inline_schema_text(
        schema_injection: SchemaInjection, schema: dict[str, Any] | None
    ) -> str | None:
        """The schema block an inline-injecting provider's prompt carries, if any.

        Metadata keys are stripped so the model does not echo the definition back.
        """
        if schema_injection == SchemaInjection.INLINE_FULL and schema is not None:
            clean = MessageBuilder._strip_schema_metadata(schema)
            return f"<|begin_of_output_schema|> : {clean} : <|end_of_output_schema|>"
        if schema_injection == SchemaInjection.INLINE_FULL_LIST and schema is not None:
            clean = MessageBuilder._strip_schema_metadata(schema)
            return (
                f"<|begin_of_output_schema|> : list of this [{clean}] : <|end_of_output_schema|>"
            )
        if schema_injection == SchemaInjection.INLINE_FIELDS:
            return MessageBuilder._build_field_schema_instruction(schema)
        return None

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
        return (
            f"<|begin_of_output_schema|> : GENERATE JSON with the fields {fields_str} "
            ": <|end_of_output_schema|>"
        )

    @staticmethod
    def _wrap_in_roles(
        role: MessageRole,
        prompt_config: str,
        context_str: str,
        body: str,
        body_static_len: int,
        *,
        style: PromptStyle = PromptStyle.TAGGED,
        shared_prompt_len: int | None = None,
    ) -> list[LLMMessage]:
        """Wrap the assembled body into the correct message role structure."""
        prompt_static_len = _shared_len(prompt_config, shared_prompt_len)
        if role == MessageRole.SYSTEM_PLUS_USER:
            # Ollama: system=prompt, user=context
            return [
                LLMMessage(role="system", content=prompt_config, static_len=prompt_static_len),
                LLMMessage(role="user", content=context_str),
            ]

        if role == MessageRole.SYSTEM_ONLY:
            # For TAGGED style (OpenAI JSON mode): split user-supplied
            # context into a separate user message to prevent prompt
            # injection via the system message.  TAGGED_GROQ (Groq)
            # embeds context in its own tagged format inside body,
            # so it keeps the single system message.
            if style == PromptStyle.TAGGED and context_str:
                return [
                    LLMMessage(role="system", content=prompt_config, static_len=prompt_static_len),
                    LLMMessage(role="user", content=context_str),
                ]
            return [LLMMessage(role="system", content=body, static_len=body_static_len)]

        # SINGLE_USER (default)
        return [LLMMessage(role="user", content=body, static_len=body_static_len)]


def _shared_len(prompt: str, shared_prompt_len: int | None) -> int:
    return len(prompt) if shared_prompt_len is None else shared_prompt_len
