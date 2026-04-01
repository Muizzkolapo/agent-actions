"""Unified response handling for LLM provider output.

Centralises output-field wrapping and usage extraction that was previously
duplicated across every provider client.  Each provider declares its usage
extraction shape via a ``ProviderResponseConfig``; the ``ResponseBuilder``
dispatches accordingly.

Mirrors the ``MessageBuilder`` pattern from ``agent_actions.prompt.message_builder``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import LLMResponseEvent
from agent_actions.output.response.config_fields import get_default

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UsageShape(Enum):
    """How a provider exposes token usage on its response object."""

    OPENAI_COMPAT = "openai_compat"
    """``response.usage.prompt_tokens`` / ``.completion_tokens`` / ``.total_tokens``
    (OpenAI, Groq, Mistral)."""

    ANTHROPIC = "anthropic"
    """``response.usage.input_tokens`` / ``.output_tokens`` (total computed)."""

    GEMINI = "gemini"
    """``response.usage_metadata.prompt_token_count`` / ``.candidates_token_count``
    / ``.total_token_count``."""

    COHERE = "cohere"
    """``response.usage.tokens.input_tokens`` / ``.output_tokens`` (total computed)."""

    OLLAMA = "ollama"
    """``getattr(response, "prompt_eval_count")`` / ``getattr(response, "eval_count")``
    (total computed)."""

    NONE = "none"
    """No usage tracking (mock providers)."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class UsageResult:
    """Canonical token usage extracted from a provider response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ---------------------------------------------------------------------------
# Provider configuration registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderResponseConfig:
    """Declares how a provider's response should be handled."""

    usage_shape: UsageShape


PROVIDER_RESPONSE_CONFIGS: dict[str, ProviderResponseConfig] = {
    "anthropic": ProviderResponseConfig(usage_shape=UsageShape.ANTHROPIC),
    "openai": ProviderResponseConfig(usage_shape=UsageShape.OPENAI_COMPAT),
    "mistral": ProviderResponseConfig(usage_shape=UsageShape.OPENAI_COMPAT),
    "gemini": ProviderResponseConfig(usage_shape=UsageShape.GEMINI),
    "groq": ProviderResponseConfig(usage_shape=UsageShape.OPENAI_COMPAT),
    "cohere": ProviderResponseConfig(usage_shape=UsageShape.COHERE),
    "ollama": ProviderResponseConfig(usage_shape=UsageShape.OLLAMA),
    "agac-fake-provider": ProviderResponseConfig(usage_shape=UsageShape.NONE),
}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class ResponseBuilder:
    """Centralised response handling for all LLM providers.

    Provides output-field wrapping and usage extraction + event firing,
    eliminating duplication across provider clients.
    """

    # -- public API ----------------------------------------------------------

    @staticmethod
    def wrap_non_json(content: str, agent_config: dict[str, Any]) -> list[dict[str, str]]:
        """Wrap plain-text LLM output in the configured output field.

        Replaces the identical ``[{output_field: content}]`` pattern
        duplicated across all provider ``call_non_json()`` methods.
        """
        output_field: str = agent_config.get("output_field", get_default("output_field"))
        return [{output_field: content}]

    @staticmethod
    def extract_usage(response: Any, provider: str) -> UsageResult:
        """Extract token usage from a provider response.

        Dispatches to the correct extraction logic based on the provider's
        ``UsageShape`` config.
        """
        config = PROVIDER_RESPONSE_CONFIGS.get(provider)
        if config is None:
            logger.debug("Unknown provider '%s' for usage extraction, returning zeros", provider)
            return UsageResult()

        shape = config.usage_shape
        if shape == UsageShape.OPENAI_COMPAT:
            return ResponseBuilder._extract_openai_compat(response)
        if shape == UsageShape.ANTHROPIC:
            return ResponseBuilder._extract_anthropic(response)
        if shape == UsageShape.GEMINI:
            return ResponseBuilder._extract_gemini(response)
        if shape == UsageShape.COHERE:
            return ResponseBuilder._extract_cohere(response)
        if shape == UsageShape.OLLAMA:
            return ResponseBuilder._extract_ollama(response)
        # NONE
        return UsageResult()

    @staticmethod
    def record_usage_and_event(
        response: Any,
        provider: str,
        model: str,
        latency_ms: float,
        request_id: str,
    ) -> UsageResult:
        """Extract usage, store via ``set_last_usage``, and fire ``LLMResponseEvent``.

        Returns the ``UsageResult`` so callers that need token counts
        (e.g. Anthropic's return tuple) can still access them.
        """
        usage = ResponseBuilder.extract_usage(response, provider)

        if usage.prompt_tokens > 0 or usage.completion_tokens > 0:
            set_last_usage(
                {
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
            )

        fire_event(
            LLMResponseEvent(
                provider=provider,
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        return usage

    # -- per-shape extractors ------------------------------------------------

    @staticmethod
    def _extract_openai_compat(response: Any) -> UsageResult:
        """OpenAI / Groq / Mistral: ``response.usage.prompt_tokens`` etc."""
        if response is None or not response.usage:
            return UsageResult()
        return UsageResult(
            prompt_tokens=response.usage.prompt_tokens or 0,
            completion_tokens=response.usage.completion_tokens or 0,
            total_tokens=response.usage.total_tokens or 0,
        )

    @staticmethod
    def _extract_anthropic(response: Any) -> UsageResult:
        """Anthropic: ``response.usage.input_tokens`` / ``.output_tokens``."""
        if response is None or not response.usage:
            return UsageResult()
        input_tokens = response.usage.input_tokens or 0
        output_tokens = response.usage.output_tokens or 0
        return UsageResult(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    @staticmethod
    def _extract_gemini(response: Any) -> UsageResult:
        """Gemini: ``response.usage_metadata.prompt_token_count`` etc."""
        if not hasattr(response, "usage_metadata") or not response.usage_metadata:
            return UsageResult()
        return UsageResult(
            prompt_tokens=response.usage_metadata.prompt_token_count or 0,
            completion_tokens=response.usage_metadata.candidates_token_count or 0,
            total_tokens=response.usage_metadata.total_token_count or 0,
        )

    @staticmethod
    def _extract_cohere(response: Any) -> UsageResult:
        """Cohere: ``response.usage.tokens.input_tokens`` etc."""
        if not hasattr(response, "usage") or not response.usage:
            return UsageResult()
        if not hasattr(response.usage, "tokens") or not response.usage.tokens:
            return UsageResult()
        tokens = response.usage.tokens
        input_tokens = tokens.input_tokens or 0
        output_tokens = tokens.output_tokens or 0
        return UsageResult(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    @staticmethod
    def _extract_ollama(response: Any) -> UsageResult:
        """Ollama: ``getattr(response, "prompt_eval_count")`` etc."""
        prompt_tokens = getattr(response, "prompt_eval_count", None) or 0
        completion_tokens = getattr(response, "eval_count", None) or 0
        return UsageResult(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
