"""
Shared helper for extracting generation parameters from agent config.

Eliminates repetitive `if agent_config.get("param") is not None` blocks
across all LLM provider clients by centralising the extraction logic
with vendor-specific key mapping and stop-sequence normalisation.
"""

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from agent_actions.config.defaults import LLMDefaults

# Core generation parameters checked by all providers
_CORE_PARAMS = ("temperature", "max_tokens", "top_p", "stop")

VENDOR_PARAMS_KEY = "vendor_params"

# Every generation setting a client sends, under its canonical name.
GENERATION_PARAMS = (*_CORE_PARAMS, "frequency_penalty", "presence_penalty", VENDOR_PARAMS_KEY)

# Set by agac on every vendor: the model, the prompt, the schema, streaming and the timeout.
ALWAYS_RESERVED = frozenset({"model", "messages", "tools", "system", "stream", "timeout"})


def sdk_keyword_params(fn: Callable[..., Any]) -> frozenset[str]:
    """The named parameters *fn* takes, without ``self`` and ``*args``/``**kwargs``."""
    return frozenset(
        name
        for name, param in inspect.signature(fn).parameters.items()
        if name != "self"
        and param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    )


@dataclass(frozen=True)
class VendorParamSpec:
    """Which ``vendor_params`` keys a vendor's request takes, and how they join it.

    *accepted* is every keyword of the SDK request (``None``: any key). *reserved* are
    the keys agac sets itself. A key in *merged* whose value is a dict is merged into
    the dict agac built under that key, the workflow's entries winning; every other
    key replaces agac's value.
    """

    accepted: frozenset[str] | None
    reserved: frozenset[str] = ALWAYS_RESERVED
    merged: frozenset[str] = frozenset()

    def allowed(self) -> list[str] | None:
        """The keys a workflow may set, sorted; ``None`` when any key passes."""
        if self.accepted is None:
            return None
        return sorted(self.accepted - self.reserved)

    def defects(self, vendor_params: Mapping[str, Any]) -> list[str]:
        """One message for each key the vendor does not take or agac sets itself."""
        problems: list[str] = []
        allowed = self.allowed()
        for key in vendor_params:
            if key in self.reserved:
                problems.append(f"'{key}' is set by agac and cannot be passed through")
            elif allowed is not None and key not in allowed:
                problems.append(
                    f"'{key}' is not a request parameter; valid keys: {', '.join(allowed)}"
                )
        return problems

    def apply(self, request: dict[str, Any], agent_config: Mapping[str, Any]) -> dict[str, Any]:
        """*request* with the action's ``vendor_params`` joined in."""
        return self._join(request, agent_config.get(VENDOR_PARAMS_KEY) or {})

    def apply_to_body(
        self, body: dict[str, Any], vendor_params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """A batch request *body* with *vendor_params* joined in.

        A batch line is the request's JSON body: ``extra_body`` joins it at the top, and
        ``extra_headers`` and ``extra_query`` have nowhere to go.
        """
        params = dict(vendor_params or {})
        extra_body = params.pop("extra_body", None)
        params.pop("extra_headers", None)
        params.pop("extra_query", None)
        if isinstance(extra_body, dict):
            params = {**extra_body, **params}
        return self._join(body, params)

    def _join(self, request: dict[str, Any], vendor_params: Mapping[str, Any]) -> dict[str, Any]:
        for key, value in vendor_params.items():
            if key in self.reserved:
                continue
            current = request.get(key)
            if key in self.merged and isinstance(current, dict) and isinstance(value, dict):
                request[key] = {**current, **value}
            else:
                request[key] = value
        return request


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
