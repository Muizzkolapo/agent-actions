"""
Shared helper for extracting generation parameters from agent config.

Eliminates repetitive `if agent_config.get("param") is not None` blocks
across all LLM provider clients by centralising the extraction logic
with vendor-specific key mapping and stop-sequence normalisation.
"""

from collections.abc import Sequence
from typing import Any

import httpx

from agent_actions.config.defaults import LLMDefaults

# Core generation parameters checked by all providers
_CORE_PARAMS = ("temperature", "max_tokens", "top_p", "stop")

# Every generation setting a client sends, under its canonical name.
GENERATION_PARAMS = (*_CORE_PARAMS, "frequency_penalty", "presence_penalty")


def extract_generation_params(
    agent_config: dict[str, Any],
    *,
    key_map: dict[str, str] | None = None,
    stop_as_list: bool = False,
    extra_params: Sequence[str] = (),
) -> dict[str, Any]:
    """Extract generation parameters from agent config with vendor-specific key mapping.

    Args:
        agent_config: Agent configuration dict.
        key_map: Mapping from canonical param name to vendor-specific API key.
            e.g. ``{"max_tokens": "max_output_tokens", "stop": "stop_sequences"}``
            Unmapped params use their canonical name.
        stop_as_list: If True, wrap a scalar ``stop`` string in a list.
            Required by Anthropic, Gemini, Cohere, and Ollama.
        extra_params: Additional param names to extract beyond the core four
            (temperature, max_tokens, top_p, stop).
            e.g. ``("frequency_penalty", "presence_penalty")`` for OpenAI.

    Returns:
        Dict of vendor-specific parameter names to values.
        Only includes params whose value in *agent_config* is not ``None``.
    """
    mapping = key_map or {}
    result: dict[str, Any] = {}

    for param in (*_CORE_PARAMS, *extra_params):
        value = agent_config.get(param)
        if value is None:
            continue
        if stop_as_list and param == "stop" and isinstance(value, str):
            value = [value]
        result[mapping.get(param, param)] = value

    return result


def request_timeout_seconds(agent_config: dict[str, Any]) -> float:
    """The action's ``request_timeout``, or the default when it is unset or null.

    Never ``None``: every provider SDK reads that as no timeout at all, so one
    stalled request would hold the run forever.
    """
    timeout = agent_config.get("request_timeout")
    return LLMDefaults.REQUEST_TIMEOUT_SECONDS if timeout is None else timeout


def request_timeout_kwargs(agent_config: dict[str, Any]) -> dict[str, Any]:
    """The action's request timeout as an SDK's ``timeout`` kwarg."""
    return {"timeout": request_timeout_seconds(agent_config)}


def connect_limited_timeout(seconds: float) -> httpx.Timeout:
    """*seconds* for the request, with the short connect limit the openai-style SDKs keep.

    A bare number would set the connect timeout to *seconds* as well.
    """
    return httpx.Timeout(seconds, connect=LLMDefaults.CONNECT_TIMEOUT_SECONDS)


def connect_limited_timeout_kwargs(agent_config: dict[str, Any]) -> dict[str, Any]:
    """The action's request timeout as the ``timeout`` kwarg of an SDK that takes httpx's."""
    return {"timeout": connect_limited_timeout(request_timeout_seconds(agent_config))}
