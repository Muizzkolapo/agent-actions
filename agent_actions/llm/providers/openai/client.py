"""
OpenAI client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for OpenAI API integration, supporting GPT models.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

import openai
from openai import OpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam

from agent_actions.errors import VendorAPIError
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="openai",
    rate_limit_types=(openai.RateLimitError,),
    network_error_types=(
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.InternalServerError,
    ),
    base_api_error_type=openai.APIError,
    supports_retry_after=True,
)


def _wrap_openai_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap OpenAI SDK errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


class OpenAIClient(BaseClient):
    """OpenAI API client for JSON and non-JSON LLM invocations."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    }

    @staticmethod
    def call_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        client = OpenAI(api_key=api_key)
        model_name: str = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build(
            "openai", prompt_config, context_data, schema=schema, json_mode=True
        )
        messages: list[ChatCompletionSystemMessageParam] = envelope.to_dicts()  # type: ignore[assignment]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        fire_event(
            LLMRequestEvent(
                provider="openai",
                model=model_name,
                request_id=request_id,
            )
        )

        completion_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": schema},
            **extract_generation_params(
                agent_config,
                extra_params=("frequency_penalty", "presence_penalty"),
            ),
        }

        start_time = datetime.now()
        try:
            response = client.chat.completions.create(**completion_kwargs)
        except openai.APIError as e:
            raise _wrap_openai_error(e, model_name, request_id) from e
        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            response, "openai", model_name, latency_ms, request_id
        )

        response_message = response.choices[0].message
        response_content: str | None = response_message.content
        if response_content is None:
            fire_event(
                LLMErrorEvent(
                    provider="openai",
                    model=model_name,
                    error_type="EmptyResponse",
                    error_message="Empty response content from OpenAI API",
                    request_id=request_id,
                )
            )
            raise VendorAPIError(
                "Empty response content from OpenAI API",
                context={
                    "model_name": model_name,
                    "vendor": "openai",
                    "api_operation": "chat.completions.create",
                },
            )
        try:
            response_data: dict[str, Any] | list[dict[str, Any]] = json.loads(response_content)
        except json.JSONDecodeError as e:
            logger.warning(
                "Failed to parse JSON from OpenAI response: %s",
                e,
                extra={"model": model_name, "operation": "call_json"},
            )
            fire_event(
                LLMErrorEvent(
                    provider="openai",
                    model=model_name,
                    error_type="JSONDecodeError",
                    error_message=f"Failed to parse JSON from response: {e}",
                    request_id=request_id,
                )
            )
            raise VendorAPIError(
                f"Failed to parse JSON response from OpenAI: {e}",
                context={
                    "model_name": model_name,
                    "vendor": "openai",
                    "api_operation": "chat.completions.create",
                    "raw_response_snippet": response_content[:200],
                },
            ) from e
        response_list: list[dict[str, Any]] = (
            response_data if isinstance(response_data, list) else [response_data]
        )
        return response_list

    @staticmethod
    def call_non_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        client = OpenAI(api_key=api_key)
        model_name: str = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build("openai", prompt_config, context_data, json_mode=False)
        messages: list[ChatCompletionUserMessageParam] = envelope.to_dicts()  # type: ignore[assignment]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        fire_event(
            LLMRequestEvent(
                provider="openai",
                model=model_name,
                request_id=request_id,
            )
        )

        completion_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            **extract_generation_params(
                agent_config,
                extra_params=("frequency_penalty", "presence_penalty"),
            ),
        }

        start_time = datetime.now()
        try:
            response = client.chat.completions.create(**completion_kwargs)
        except openai.APIError as e:
            raise _wrap_openai_error(e, model_name, request_id) from e
        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            response, "openai", model_name, latency_ms, request_id
        )

        response_message = response.choices[0].message
        content: str | None = response_message.content
        if content is None:
            fire_event(
                LLMErrorEvent(
                    provider="openai",
                    model=model_name,
                    error_type="EmptyResponse",
                    error_message="Empty response content from OpenAI API",
                    request_id=request_id,
                )
            )
            raise VendorAPIError(
                "Empty response content from OpenAI API",
                context={
                    "model_name": model_name,
                    "vendor": "openai",
                    "api_operation": "chat.completions.create",
                    "output_field": agent_config.get("output_field", "raw_response"),
                },
            )
        return ResponseBuilder.wrap_non_json(content, agent_config)
