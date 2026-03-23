"""
Groq LLM client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for Groq API integration, supporting models like Llama3.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.

JSON parse failures return error dicts for RepromptEngine repair support,
as Groq's json_object mode can produce malformed output.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, ClassVar

import groq
from groq import Groq

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.input.preprocessing.transformation.transformer import DataTransformer
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.llm.providers.mixins import JSONResponseMixin
from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
    LLMResponseEvent,
)
from agent_actions.output.response.config_fields import get_default
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

logger = logging.getLogger(__name__)


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


def _wrap_groq_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Groq SDK errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


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

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        client = Groq(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build(
            "groq", prompt_config, context_data, schema=schema, json_mode=True
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
            "response_format": {"type": "json_object"},
            **extract_generation_params(
                agent_config, extra_params=("frequency_penalty", "presence_penalty")
            ),
        }

        start_time = datetime.now()
        try:
            llm = client.chat.completions.create(**json_completion_kwargs)
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except groq.APIError as e:
            raise _wrap_groq_error(e, model_name, request_id) from e
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

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        # Extract token usage (OpenAI-compatible format)
        prompt_tokens = llm.usage.prompt_tokens if llm.usage else 0
        completion_tokens = llm.usage.completion_tokens if llm.usage else 0
        total_tokens = llm.usage.total_tokens if llm.usage else 0

        if llm.usage:
            set_last_usage(
                {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            )

        # Fire LLM response event
        fire_event(
            LLMResponseEvent(
                provider="groq",
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        response_temp = llm.choices[0].message.content
        response_data = GroqClient.parse_json_response(
            response_temp, "Groq", "call_json", model_name
        )
        return DataTransformer.ensure_list(response_data)

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        client = Groq(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build("groq", prompt_config, context_data, json_mode=False)
        params = extract_generation_params(agent_config)
        params.setdefault("temperature", 0.7)
        params.setdefault("max_tokens", 1000)
        completion_kwargs = {
            "messages": envelope.to_dicts(),
            "model": model_name,
            **params,
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

        start_time = datetime.now()
        try:
            response = client.chat.completions.create(**completion_kwargs)
        except groq.APIError as e:
            raise _wrap_groq_error(e, model_name, request_id) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        # Extract token usage (OpenAI-compatible format)
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        total_tokens = response.usage.total_tokens if response.usage else 0

        if response.usage:
            set_last_usage(
                {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            )

        # Fire LLM response event
        fire_event(
            LLMResponseEvent(
                provider="groq",
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        try:
            response_content = response.choices[0].message.content
            output_field = agent_config.get("output_field", get_default("output_field"))
            return [{output_field: response_content}]
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
