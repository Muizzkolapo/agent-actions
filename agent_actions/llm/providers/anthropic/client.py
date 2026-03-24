"""
Anthropic Claude client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for Anthropic's Claude API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar

import anthropic

from agent_actions.errors import VendorAPIError
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="anthropic",
    rate_limit_types=(anthropic.RateLimitError,),
    network_error_types=(
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.InternalServerError,
    ),
    base_api_error_type=anthropic.APIError,
    supports_retry_after=True,
)


def _wrap_anthropic_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Anthropic SDK errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


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

    @staticmethod
    def _build_api_args(
        model_name: str,
        prompt_dedent: str,
        schema: dict[str, Any] | None,
        agent_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build API arguments for the Anthropic call."""
        cfg = agent_config or {}
        params = extract_generation_params(
            cfg,
            key_map={"stop": "stop_sequences"},
            stop_as_list=True,
        )
        # max_tokens is always required for Anthropic; default 1024
        params.setdefault("max_tokens", 1024)

        api_args: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt_dedent}],
            **params,
        }
        if schema is not None:
            api_args["tools"] = schema
        return api_args

    @staticmethod
    def _extract_response_content(
        response: Any, model_name: str
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Extract content from response, raising error if not found."""
        response_content = next(
            (block.input for block in response.content if hasattr(block, "input")), None
        )
        if response_content is not None:
            return response_content  # type: ignore[no-any-return]

        text_content = next(
            (block.text for block in response.content if hasattr(block, "text")),
            "No text content available",
        )
        raise VendorAPIError(
            "No valid content with 'input' found in response",
            context={
                "model_name": model_name,
                "vendor": "anthropic",
                "text_content": text_content[:200],
                "api_operation": "messages.create",
            },
        )

    @staticmethod
    def _call_api(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
        mode: str,
    ) -> tuple:
        """Shared API call with timing, usage tracking, and event handling.

        Returns:
            Tuple of (response, model_name, request_id).
        """
        model_name: str = agent_config[MODEL_NAME_KEY]
        client = anthropic.Anthropic(api_key=api_key)
        json_mode = schema is not None
        envelope = MessageBuilder.build(
            "anthropic", prompt_config, context_data, schema=schema, json_mode=json_mode
        )
        prompt_dedent: str = envelope.messages[0].content

        api_args = AnthropicClient._build_api_args(model_name, prompt_dedent, schema, agent_config)

        request_id = str(uuid.uuid4())

        fire_event(
            LLMRequestEvent(
                provider="anthropic",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            response = client.messages.create(**api_args)
        except anthropic.APIError as e:
            raise _wrap_anthropic_error(e, model_name, request_id) from e
        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

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
            api_key, agent_config, prompt_config, context_data, schema, "json"
        )
        try:
            result = AnthropicClient._extract_response_content(response, model_name)
            return result if isinstance(result, list) else [result]
        except VendorAPIError as e:
            fire_event(
                LLMErrorEvent(
                    provider="anthropic",
                    model=model_name,
                    error_type="ContentExtractionError",
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            raise

    @staticmethod
    def call_non_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Plain-text (non-JSON) mode for Claude."""
        response, model_name, request_id = AnthropicClient._call_api(
            api_key, agent_config, prompt_config, context_data, None, "non_json"
        )

        content = next(
            (block.text for block in response.content if hasattr(block, "text")),
            None,
        )
        if content is None:
            fire_event(
                LLMErrorEvent(
                    provider="anthropic",
                    model=model_name,
                    error_type="EmptyResponse",
                    error_message="Empty response content from Anthropic API",
                    request_id=request_id,
                )
            )
            raise VendorAPIError(
                "Empty response content from Anthropic API",
                context={
                    "model_name": model_name,
                    "vendor": "anthropic",
                    "api_operation": "messages.create",
                },
            )

        return ResponseBuilder.wrap_non_json(content, agent_config)
