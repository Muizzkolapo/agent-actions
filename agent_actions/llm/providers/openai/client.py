"""
OpenAI client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for OpenAI API integration, supporting GPT models.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import time
import uuid
from dataclasses import replace
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

import openai
from openai import OpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam

from agent_actions.errors import VendorAPIError
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import (
    extract_generation_params,
    request_timeout_kwargs,
)
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


class OpenAIClient(BaseClient):
    """OpenAI API client for JSON and non-JSON LLM invocations."""

    # The vendor its events and errors name; a runtime profile client sets its own.
    VENDOR: ClassVar[str] = "openai"

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "base_url", "temperature", "max_tokens"],
    }

    @classmethod
    def _error_mapping(cls) -> VendorErrorMapping:
        return replace(_ERROR_MAPPING, vendor_name=cls.VENDOR)

    @classmethod
    def _client_options(cls, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Constructor kwargs for the SDK client; a declared endpoint adds headers and a timeout."""
        return {"base_url": agent_config.get("base_url")}

    @classmethod
    def call_json(
        cls,
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        from agent_actions.llm.providers.client_base import get_or_create_client

        client = get_or_create_client(OpenAI, api_key, **cls._client_options(agent_config))
        model_name: str = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build(
            "openai",
            prompt_config,
            context_data,
            schema=schema,
            json_mode=True,
            model_name=model_name,
        )
        messages: list[ChatCompletionSystemMessageParam] = envelope.to_dicts()  # type: ignore[assignment]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        fire_event(
            LLMRequestEvent(
                provider=cls.VENDOR,
                model=model_name,
                request_id=request_id,
            )
        )

        completion_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "response_format": (
                {"type": "json_schema", "json_schema": schema}
                if schema
                else {"type": "json_object"}
            ),
            **extract_generation_params(
                agent_config,
                extra_params=("frequency_penalty", "presence_penalty"),
            ),
            # Per request, so it outranks a declared endpoint's client-wide timeout.
            **request_timeout_kwargs(agent_config),
        }

        start_time = time.perf_counter()
        try:
            response = client.chat.completions.create(**completion_kwargs)
        except openai.APIError as e:
            raise wrap_vendor_error(e, model_name, cls._error_mapping(), request_id) from e
        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(
            response, cls.VENDOR, model_name, latency_ms, request_id
        )

        response_message = response.choices[0].message
        response_content: str | None = response_message.content
        if response_content is None:
            fire_event(
                LLMErrorEvent(
                    provider=cls.VENDOR,
                    model=model_name,
                    error_type="EmptyResponse",
                    error_message="Empty response content from OpenAI API",
                    request_id=request_id,
                )
            )
            logger.debug(
                "Empty response content from OpenAI API, model=%s",
                model_name,
            )
            return [{"raw_response": "", "_parse_error": "Empty response from API"}]
        from agent_actions.utils.json_parsing import parse_llm_json

        response_data = parse_llm_json(response_content)
        if isinstance(response_data, str):
            logger.debug(
                "Failed to parse JSON from OpenAI response (snippet: %.200s)",
                response_content,
                extra={"model": model_name, "operation": "call_json"},
            )
            fire_event(
                LLMErrorEvent(
                    provider=cls.VENDOR,
                    model=model_name,
                    error_type="JSONDecodeError",
                    error_message="Failed to parse JSON from response",
                    request_id=request_id,
                )
            )
            return [
                {
                    "raw_response": response_content,
                    "_parse_error": "Failed to parse JSON from LLM response",
                }
            ]
        response_list: list[dict[str, Any]] = (
            response_data if isinstance(response_data, list) else [response_data]
        )
        return response_list

    @classmethod
    def call_non_json(
        cls,
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        from agent_actions.llm.providers.client_base import get_or_create_client

        client = get_or_create_client(OpenAI, api_key, **cls._client_options(agent_config))
        model_name: str = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build("openai", prompt_config, context_data, json_mode=False)
        messages: list[ChatCompletionUserMessageParam] = envelope.to_dicts()  # type: ignore[assignment]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        fire_event(
            LLMRequestEvent(
                provider=cls.VENDOR,
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
            # Per request, so it outranks a declared endpoint's client-wide timeout.
            **request_timeout_kwargs(agent_config),
        }

        start_time = time.perf_counter()
        try:
            response = client.chat.completions.create(**completion_kwargs)
        except openai.APIError as e:
            raise wrap_vendor_error(e, model_name, cls._error_mapping(), request_id) from e
        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(
            response, cls.VENDOR, model_name, latency_ms, request_id
        )

        response_message = response.choices[0].message
        content: str | None = response_message.content
        if content is None:
            fire_event(
                LLMErrorEvent(
                    provider=cls.VENDOR,
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
                    "vendor": cls.VENDOR,
                    "api_operation": "chat.completions.create",
                    "output_field": agent_config.get("output_field", "raw_response"),
                },
            )
        return ResponseBuilder.wrap_non_json(content, agent_config)
