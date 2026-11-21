"""
Groq LLM client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for Groq API integration, supporting models like Llama3.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.

JSON parse failures return an error dict rather than raising, leaving the
caller to decide whether to regenerate; Groq's json_object mode can produce
malformed output.
"""

import logging
import time
import uuid
from typing import Any, ClassVar

import groq
from groq import Groq
from groq.types.chat import ChatCompletion

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.input.preprocessing.transformation.transformer import DataTransformer
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import (
    NoAnswer,
    VendorErrorMapping,
    chat_no_answer,
    unfinished_parse_error,
    wrap_vendor_error,
)
from agent_actions.llm.providers.generation_params import (
    ALWAYS_RESERVED,
    VendorParamSpec,
    connect_limited_timeout_kwargs,
    extract_generation_params,
    sdk_keyword_params,
)
from agent_actions.llm.providers.mixins import JSONResponseMixin
from agent_actions.llm.providers.sdk_models import build_sdk_models
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

logger = logging.getLogger(__name__)

build_sdk_models(ChatCompletion)

_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="groq",
    rate_limit_types=(groq.RateLimitError,),
    network_error_types=(
        groq.APIConnectionError,
        groq.APITimeoutError,
        groq.InternalServerError,
    ),
    base_api_error_type=groq.APIError,
    supports_retry_after=True,
)


def _no_answer(content: Any, finish_reason: Any, model_name: str) -> NoAnswer | None:
    # Groq's message carries no refusal.
    return chat_no_answer(
        content, finish_reason, None, vendor_label="Groq", model_name=model_name, vendor="groq"
    )


class GroqClient(BaseClient, JSONResponseMixin):
    """Groq API client for JSON and non-JSON LLM invocations."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": False,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    }
    VENDOR_PARAMS: ClassVar[VendorParamSpec] = VendorParamSpec(
        accepted=sdk_keyword_params(groq.resources.chat.completions.Completions.create),
        reserved=ALWAYS_RESERVED,
        merged=frozenset({"extra_headers", "extra_body", "extra_query"}),
    )

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        from agent_actions.llm.providers.client_base import get_or_create_client

        client = get_or_create_client(Groq, api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build(
            "groq",
            prompt_config,
            context_data,
            schema=schema,
            json_mode=True,
            context_window=agent_config.get("context_window"),
        )

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="groq",
                model=model_name,
                request_id=request_id,
            )
        )

        json_completion_kwargs: dict[str, Any] = {
            "messages": envelope.to_dicts(),
            "model": model_name,
            "response_format": (
                {"type": "json_schema", "json_schema": schema}
                if schema
                else {"type": "json_object"}
            ),
            **extract_generation_params(
                agent_config, extra_params=("frequency_penalty", "presence_penalty")
            ),
            **connect_limited_timeout_kwargs(agent_config, groq),
        }

        start_time = time.perf_counter()
        try:
            llm = client.chat.completions.create(
                **GroqClient.VENDOR_PARAMS.apply(json_completion_kwargs, agent_config)
            )
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except groq.APIError as e:
            raise wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="groq",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            raise VendorAPIError(
                "Failed to create chat completion with Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "api_operation": "chat.completions.create",
                },
                cause=e,
            ) from e

        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(llm, "groq", model_name, latency_ms, request_id)

        response_temp = llm.choices[0].message.content
        finish_reason = llm.choices[0].finish_reason
        ended = _no_answer(response_temp, finish_reason, model_name)
        if ended is not None:
            if response_temp is not None:
                logger.warning("%s (model=%s)", ended.parse_error, model_name)
            return [{"raw_response": "", "_parse_error": ended.parse_error}]
        parse_error = unfinished_parse_error(finish_reason)
        if parse_error:
            logger.warning("%s (model=%s)", parse_error, model_name)
            return [{"raw_response": response_temp, "_parse_error": parse_error}]
        response_data = GroqClient.parse_json_response(
            response_temp, "Groq", "call_json", model_name
        )
        return DataTransformer.ensure_list(response_data)

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        from agent_actions.llm.providers.client_base import get_or_create_client

        client = get_or_create_client(Groq, api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build(
            "groq",
            prompt_config,
            context_data,
            json_mode=False,
            context_window=agent_config.get("context_window"),
        )
        completion_kwargs = {
            "messages": envelope.to_dicts(),
            "model": model_name,
            **extract_generation_params(agent_config),
            **connect_limited_timeout_kwargs(agent_config, groq),
        }

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="groq",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = time.perf_counter()
        try:
            response = client.chat.completions.create(
                **GroqClient.VENDOR_PARAMS.apply(completion_kwargs, agent_config)
            )
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except groq.APIError as e:
            raise wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id) from e

        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(response, "groq", model_name, latency_ms, request_id)

        choice = response.choices[0] if getattr(response, "choices", None) else None
        ended = (
            _no_answer(choice.message.content, choice.finish_reason, model_name)
            if choice is not None
            else None
        )
        if ended is not None and ended.error is not None:
            raise ended.error
        try:
            response_content = response.choices[0].message.content
            return ResponseBuilder.wrap_non_json(response_content, agent_config)
        except (AttributeError, IndexError, TypeError) as e:
            fire_event(
                LLMErrorEvent(
                    provider="groq",
                    model=model_name,
                    error_type="ResponseParseError",
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            raise VendorAPIError(
                "Error parsing non-JSON response from Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "response": str(response)[:200],
                },
                cause=e,
            ) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="groq",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            raise VendorAPIError(
                "Failed to get non-JSON chat completion from Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "api_operation": "chat.completions.create",
                },
                cause=e,
            ) from e
