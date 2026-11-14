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
from typing import Any, ClassVar

import anthropic

from agent_actions.llm.providers.anthropic import (
    PROMPT_CACHING_BETA_HEADER,
    server_busy_errors,
)
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import (
    VendorErrorMapping,
    empty_response_error,
    wrap_vendor_error,
)
from agent_actions.llm.providers.generation_params import (
    VENDOR_PARAMS_KEY,
    VendorParamSpec,
    connect_limited_timeout_kwargs,
    extract_generation_params,
    sdk_keyword_params,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

logger = logging.getLogger(__name__)

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


class AnthropicClient(BaseClient):
    """Anthropic Claude API client for JSON and non-JSON LLM invocations."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens", "anthropic_version"],
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
        # max_tokens is always required for Anthropic; default 4096
        params.setdefault("max_tokens", 4096)

        api_args: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            **params,
        }
        if schema is not None:
            api_args["tools"] = schema
            tool_choice = AnthropicClient._schema_tool_choice(schema, cfg)
            if tool_choice is not None:
                api_args["tool_choice"] = tool_choice
        if enable_prompt_caching:
            api_args["extra_headers"] = PROMPT_CACHING_BETA_HEADER
        return AnthropicClient.VENDOR_PARAMS.apply(api_args, cfg)

    @staticmethod
    def _schema_tool_choice(schema: Any, cfg: dict[str, Any]) -> dict[str, Any] | None:
        """Force the one schema tool, so the model cannot answer in text instead.

        Not while thinking is on: the API refuses a forced tool with thinking.
        """
        if not isinstance(schema, list) or len(schema) != 1 or not isinstance(schema[0], dict):
            return None
        name = schema[0].get("name")
        thinking = (cfg.get(VENDOR_PARAMS_KEY) or {}).get("thinking")
        if not name or (isinstance(thinking, dict) and thinking.get("type") != "disabled"):
            return None
        return {"type": "tool", "name": name}

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
            enable_prompt_caching=enable_caching,
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
        message = f"No tool_use block in response (stop_reason={stop_reason}): {text[:200]!r}"
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
        if content is None:
            error = empty_response_error(
                "Anthropic",
                getattr(response, "stop_reason", None),
                model_name=model_name,
                vendor="anthropic",
                operation="messages.create",
            )
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
