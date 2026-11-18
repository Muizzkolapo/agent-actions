"""
Anthropic Claude client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for Anthropic's Claude API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar, TypeGuard

import anthropic
from anthropic.lib import streaming
from anthropic.types import Message, RawMessageStreamEvent

from agent_actions.llm.providers.anthropic import (
    PROMPT_CACHING_BETA_HEADER,
    server_busy_errors,
)
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import (
    NoAnswer,
    VendorErrorMapping,
    empty_response_error,
    is_truncated,
    wrap_vendor_error,
)
from agent_actions.llm.providers.generation_params import (
    VENDOR_PARAMS_KEY,
    VendorParamSpec,
    connect_limited_timeout_kwargs,
    extract_generation_params,
    sdk_keyword_params,
)
from agent_actions.llm.providers.sdk_models import build_sdk_models
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.cache_scope import SHARED_PROMPT_LEN_KEY, prompt_is_shared
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY
from agent_actions.utils.json_parsing import parse_llm_json

logger = logging.getLogger(__name__)

# A newer SDK's stream helper builds a ParsedMessage, an older one a Message.
build_sdk_models(
    Message,
    RawMessageStreamEvent,
    streaming.MessageStreamEvent,
    getattr(streaming, "ParsedMessageStreamEvent", None),
)

# The API requires max_tokens; agac sends this when the action sets none.
_DEFAULT_MAX_TOKENS = 4096

# The stop reasons of a message the model ended itself.
_OWN_STOP_REASONS = frozenset({None, "end_turn", "stop_sequence"})


def no_tool_answer_message(stop_reason: Any, text: str) -> str:
    """The parse error for a JSON-mode message that holds no tool answer and no readable text."""
    return f"No tool_use block in response (stop_reason={stop_reason}): {text[:200]!r}"


def no_answer(stop_reason: Any, *, only_text: bool, model_name: str, operation: str) -> NoAnswer:
    """How a message with no tool answer and no text ends, online and in a batch result.

    ``only_text`` says the message holds nothing but text blocks, which are then empty. Such
    a message the model ended itself is an empty answer, left to the action's ``on_empty``.
    One that was stopped, or that holds other blocks only (thinking), is an error naming
    the stop reason.
    """
    parse_error = no_tool_answer_message(stop_reason, "")
    if only_text and stop_reason in _OWN_STOP_REASONS:
        return NoAnswer(parse_error=parse_error)
    return NoAnswer(
        parse_error=parse_error,
        error=empty_response_error(
            "Anthropic", stop_reason, model_name=model_name, vendor="anthropic", operation=operation
        ),
    )


# The SDK refuses a non-streamed request it expects to run past 10 minutes: at 128,000
# output tokens an hour, that is any max_tokens above 21,333.
_NONSTREAMING_MAX_TOKENS = 21_333

_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="anthropic",
    rate_limit_types=(anthropic.RateLimitError,),
    network_error_types=(
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.InternalServerError,
        *server_busy_errors(anthropic),
    ),
    base_api_error_type=anthropic.APIError,
    supports_retry_after=True,
)


def _model_nonstreaming_limit(model: str) -> int | None:
    """The SDK's lower non-streaming max_tokens for *model*, where it keeps one."""
    try:
        from anthropic._constants import MODEL_NONSTREAMING_TOKENS
    except ImportError:
        return None
    return MODEL_NONSTREAMING_TOKENS.get(model)


def json_answer_in(text: str) -> dict[str, Any] | list[dict[str, Any]] | None:
    """The JSON answer a text reply holds, an object or a list of objects; None for any other."""
    parsed = parse_llm_json(text)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list) and parsed and all(isinstance(item, dict) for item in parsed):
        return parsed
    return None


def _sends_interleaved_thinking(vendor_params: Mapping[str, Any]) -> bool:
    """Whether the request carries the beta that lets a thinking budget exceed max_tokens."""
    headers = vendor_params.get("extra_headers")
    beta = headers.get("anthropic-beta") if isinstance(headers, dict) else None
    return isinstance(beta, str) and "interleaved-thinking" in beta


class AnthropicClient(BaseClient):
    """Anthropic Claude API client for JSON and non-JSON LLM invocations."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    }
    VENDOR_PARAMS: ClassVar[VendorParamSpec] = VendorParamSpec(
        accepted=sdk_keyword_params(anthropic.resources.messages.Messages.create),
        merged=frozenset({"extra_headers", "extra_body", "extra_query"}),
    )

    @staticmethod
    def _build_api_args(
        model_name: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None,
        agent_config: dict[str, Any] | None = None,
        *,
        enable_prompt_caching: bool = False,
    ) -> dict[str, Any]:
        """Build API arguments for the Anthropic call."""
        cfg = agent_config or {}
        params = extract_generation_params(
            cfg,
            key_map={"stop": "stop_sequences"},
            stop_as_list=True,
        )
        params.setdefault("max_tokens", _DEFAULT_MAX_TOKENS)

        api_args: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            **params,
        }
        # The tool is offered, not forced: forced, claude-haiku-5-5 returns a nested array as
        # one JSON string, which no repair undoes. vendor_params.tool_choice can force it.
        if schema is not None:
            api_args["tools"] = schema
        if enable_prompt_caching:
            api_args["extra_headers"] = PROMPT_CACHING_BETA_HEADER
        spec = AnthropicClient.VENDOR_PARAMS
        return spec.apply(spec.fit(api_args), cfg)

    @staticmethod
    def vendor_params_conflicts(agent_config: Mapping[str, Any]) -> list[str]:
        """What the API refuses beside the action's ``vendor_params.thinking``, one line each.

        With thinking on, Anthropic takes temperature 1 only, top_p of 0.95 or more, no
        top_k and no forced tool; an enabled thinking's ``budget_tokens`` must be below
        ``max_tokens``, unless the interleaved-thinking beta lets it run past.
        """
        vendor_params = agent_config.get(VENDOR_PARAMS_KEY) or {}
        thinking = vendor_params.get("thinking")
        if not isinstance(thinking, dict) or thinking.get("type") in (None, "disabled"):
            return []

        extra_body = vendor_params.get("extra_body")
        sources = (vendor_params, extra_body if isinstance(extra_body, dict) else {}, agent_config)

        def sent(key: str) -> Any:
            return next((src[key] for src in sources if src.get(key) is not None), None)

        def number(value: Any) -> TypeGuard[int | float]:
            return isinstance(value, int | float) and not isinstance(value, bool)

        problems: list[str] = []
        temperature, top_p, top_k = sent("temperature"), sent("top_p"), sent("top_k")
        if number(temperature) and temperature != 1:
            problems.append(f"with thinking on, temperature must be 1 or unset, not {temperature}")
        if number(top_p) and top_p < 0.95:
            problems.append(f"with thinking on, top_p must be 0.95 or more, or unset, not {top_p}")
        if top_k is not None:
            problems.append(f"with thinking on, top_k must be unset, not {top_k}")
        tool_choice = sent("tool_choice")
        forced = tool_choice.get("type") if isinstance(tool_choice, dict) else None
        if forced in ("any", "tool"):
            problems.append(
                f"with thinking on, tool_choice cannot force a tool (type {forced!r}); "
                "use auto or none"
            )

        budget = thinking.get("budget_tokens")
        max_tokens = sent("max_tokens")
        limit = max_tokens if number(max_tokens) else _DEFAULT_MAX_TOKENS
        if (
            thinking.get("type") == "enabled"
            and number(budget)
            and budget >= limit
            and not _sends_interleaved_thinking(vendor_params)
        ):
            named = limit if number(max_tokens) else f"{limit}, the default"
            problems.append(f"thinking.budget_tokens ({budget}) must be below max_tokens ({named})")
        return problems

    @staticmethod
    def _needs_streaming(api_args: dict[str, Any]) -> bool:
        """Whether the SDK would refuse *api_args* as a non-streamed request."""
        max_tokens = api_args.get("max_tokens") or 0
        model_limit = _model_nonstreaming_limit(api_args.get("model", ""))
        return max_tokens > _NONSTREAMING_MAX_TOKENS or (
            model_limit is not None and max_tokens > model_limit
        )

    @staticmethod
    def _call_api(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> tuple:
        """Shared API call with timing, usage tracking, and event handling.

        Returns:
            Tuple of (response, model_name, request_id).
        """
        model_name: str = agent_config[MODEL_NAME_KEY]
        from agent_actions.llm.providers.client_base import get_or_create_client

        client = get_or_create_client(anthropic.Anthropic, api_key)
        json_mode = schema is not None
        enable_caching = agent_config.get("enable_prompt_caching", False)
        envelope = MessageBuilder.build(
            "anthropic",
            prompt_config,
            context_data,
            schema=schema,
            json_mode=json_mode,
            enable_prompt_caching=enable_caching and prompt_is_shared(agent_config),
            shared_prompt_len=agent_config.get(SHARED_PROMPT_LEN_KEY),
            model_name=model_name,
        )
        messages = envelope.to_dicts()

        api_args = AnthropicClient._build_api_args(
            model_name, messages, schema, agent_config, enable_prompt_caching=enable_caching
        )

        request_id = str(uuid.uuid4())

        fire_event(
            LLMRequestEvent(
                provider="anthropic",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = time.perf_counter()
        try:
            timeout = connect_limited_timeout_kwargs(agent_config, anthropic)
            if AnthropicClient._needs_streaming(api_args):
                with client.messages.stream(**api_args, **timeout) as stream:
                    response = stream.get_final_message()
            else:
                response = client.messages.create(**api_args, **timeout)
        except anthropic.APIError as e:
            raise wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id) from e
        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(
            response, "anthropic", model_name, latency_ms, request_id
        )

        return response, model_name, request_id

    @staticmethod
    def call_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        response, model_name, request_id = AnthropicClient._call_api(
            api_key, agent_config, prompt_config, context_data, schema
        )
        tool_input = next(
            (block.input for block in response.content if hasattr(block, "input")), None
        )
        if tool_input is not None:
            return tool_input if isinstance(tool_input, list) else [tool_input]

        text = next((block.text for block in response.content if hasattr(block, "text")), "")
        stop_reason = getattr(response, "stop_reason", None)
        # Offered the tool, a model can answer in text instead, often in a ```json fence.
        # A finished answer is read like every other client's; a cut-off one could only be
        # read by guessing its end.
        if text and not is_truncated(stop_reason):
            answer = json_answer_in(text)
            if answer is not None:
                logger.debug(
                    "Anthropic model=%s answered in text, not the tool; read it as JSON",
                    model_name,
                )
                return answer if isinstance(answer, list) else [answer]
        message = no_tool_answer_message(stop_reason, text)
        fire_event(
            LLMErrorEvent(
                provider="anthropic",
                model=model_name,
                error_type="EmptyResponse",
                error_message=message,
                request_id=request_id,
            )
        )
        logger.warning("Anthropic model=%s: %s", model_name, message)
        return [{"raw_response": text, "_parse_error": message}]

    @staticmethod
    def call_non_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Plain-text (non-JSON) mode for Claude."""
        response, model_name, request_id = AnthropicClient._call_api(
            api_key, agent_config, prompt_config, context_data, None
        )

        content = next(
            (block.text for block in response.content if hasattr(block, "text")),
            None,
        )
        if not content:
            error = no_answer(
                getattr(response, "stop_reason", None),
                only_text=all(hasattr(block, "text") for block in response.content),
                model_name=model_name,
                operation="messages.create",
            ).error
            if error is None:
                return []
            fire_event(
                LLMErrorEvent(
                    provider="anthropic",
                    model=model_name,
                    error_type="EmptyResponse",
                    error_message=str(error),
                    request_id=request_id,
                )
            )
            raise error

        return ResponseBuilder.wrap_non_json(content, agent_config)
