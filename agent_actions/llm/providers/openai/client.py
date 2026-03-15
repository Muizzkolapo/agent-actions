"""
OpenAI client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for OpenAI API integration, supporting GPT models.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import json
import uuid
from datetime import datetime
from textwrap import dedent
from typing import Any, ClassVar

import openai
from openai import OpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam

from agent_actions.errors import VendorAPIError
from agent_actions.input.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
    LLMResponseEvent,
)
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
        prompt_config: dict[str, Any],
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        client = OpenAI(api_key=api_key)
        model_name: str = agent_config[MODEL_NAME_KEY]
        context_data_str: str = StringProcessor.process_as_string(context_data)
        prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            RULES: ALWAYS READ INPUT AS STRING\n        "
        messages: list[ChatCompletionSystemMessageParam] = [
            {"role": "system", "content": dedent(prompt)}
        ]

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

        # Extract token usage and store in thread-local
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        total_tokens = response.usage.total_tokens if response.usage else 0

        if response.usage:
            usage_data = {
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
            set_last_usage(usage_data)

        # Fire LLM response event
        fire_event(
            LLMResponseEvent(
                provider="openai",
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
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
        response_data: dict[str, Any] | list[dict[str, Any]] = json.loads(response_content)
        response_list: list[dict[str, Any]] = (
            response_data if isinstance(response_data, list) else [response_data]
        )
        return response_list

    @staticmethod
    def call_non_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: dict[str, Any],
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        client = OpenAI(api_key=api_key)
        model_name: str = agent_config[MODEL_NAME_KEY]
        context_data_str: str = StringProcessor.process_as_string(context_data)
        prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
        messages: list[ChatCompletionUserMessageParam] = [
            {"role": "user", "content": dedent(prompt)}
        ]

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

        # Extract token usage and store in thread-local
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        total_tokens = response.usage.total_tokens if response.usage else 0

        if response.usage:
            usage_data = {
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
            set_last_usage(usage_data)

        # Fire LLM response event
        fire_event(
            LLMResponseEvent(
                provider="openai",
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        response_message = response.choices[0].message
        output_field: str = agent_config.get("output_field", "raw_response")
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
                    "output_field": output_field,
                },
            )
        response_content: dict[str, str] = {output_field: content}
        return [response_content]
