"""
Cohere client for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for Cohere API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, ClassVar

import cohere
from cohere.core import api_error as cohere_errors

from agent_actions.errors import ConfigurationError, NetworkError, RateLimitError, VendorAPIError
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.llm.providers.mixins import (
    GenericErrorHandlerMixin,
    JSONResponseMixin,
)
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

logger = logging.getLogger(__name__)


_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="cohere",
    status_code_error_types=(cohere_errors.ApiError,),
    extra_network_types=(ConnectionError, TimeoutError),
    supports_retry_after=False,
)


def _wrap_cohere_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Cohere SDK errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


class CohereClient(BaseClient, JSONResponseMixin, GenericErrorHandlerMixin):
    """Cohere API client for JSON and non-JSON LLM invocations."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": False,
        "supports_tools": True,
        "supports_vision": False,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    }

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Validate schema before firing LLMRequestEvent
        # so a validation error doesn't orphan the request event in the log.
        if schema is not None:
            if not schema:
                raise ConfigurationError("Schema must not be empty")
            if "properties" not in schema:
                if schema.get("type") == "object":
                    raise ConfigurationError(
                        f"Schema is a JSON Schema object but missing 'properties' key (got: {list(schema.keys())})"
                    )
                if not all(isinstance(v, dict) for v in schema.values()):
                    raise ConfigurationError(
                        f"Schema is neither a JSON Schema nor a valid field dict "
                        f"(keys: {list(schema.keys())})"
                    )

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="cohere",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            co = cohere.ClientV2(api_key=api_key)
            envelope = MessageBuilder.build(
                "cohere", prompt_config, context_data, schema=schema, json_mode=True
            )
            messages = envelope.to_dicts()
            chat_kwargs = {
                "model": model_name,
                "messages": messages,
                "response_format": {"type": "json_object"},
                **extract_generation_params(
                    agent_config,
                    key_map={"top_p": "p", "stop": "stop_sequences"},
                    stop_as_list=True,
                ),
            }
            response = co.chat(**chat_kwargs)
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except cohere_errors.ApiError as e:
            raise _wrap_cohere_error(e, model_name, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="cohere",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            CohereClient.handle_generic_error(e, "Cohere", "call_json", model_name)

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            response, "cohere", model_name, latency_ms, request_id
        )

        # Guard against empty or missing content in Cohere v2 response
        if not hasattr(response, "message") or not response.message or not response.message.content:
            raise VendorAPIError(
                "Cohere JSON response contained no content",
                vendor="cohere",
            )
        intermediate_json = response.message.content[0].text  # type: ignore[union-attr]

        result = CohereClient.parse_json_response(
            response_content=intermediate_json,
            vendor_name="Cohere",
            operation="call_json",
            model_name=model_name,
        )
        return result if isinstance(result, list) else [result]

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="cohere",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            co = cohere.ClientV2(api_key=api_key)
            envelope = MessageBuilder.build("cohere", prompt_config, context_data, json_mode=False)
            messages = envelope.to_dicts()
            non_json_kwargs = {
                "model": model_name,
                "messages": messages,
                **extract_generation_params(
                    agent_config,
                    key_map={"top_p": "p", "stop": "stop_sequences"},
                    stop_as_list=True,
                ),
            }
            response = co.chat(**non_json_kwargs)
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except cohere_errors.ApiError as e:
            raise _wrap_cohere_error(e, model_name, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="cohere",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            logger.exception(
                "Cohere non-JSON API call failed",
                extra={
                    "operation": "cohere_call_non_json",
                    "model": model_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                },
            )
            raise VendorAPIError(
                f"Cohere non-JSON API call failed: {e}",
                vendor="cohere",
                cause=e,
            ) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            response, "cohere", model_name, latency_ms, request_id
        )

        # Guard against empty or missing content in Cohere v2 response
        if not hasattr(response, "message") or not response.message or not response.message.content:
            raise VendorAPIError(
                "Cohere non-JSON response contained no content",
                vendor="cohere",
            )
        response_message = response.message.content[0].text  # type: ignore[union-attr]

        logger.debug(
            "Cohere non-JSON response retrieved successfully",
            extra={
                "operation": "cohere_call_non_json",
                "model": model_name,
                "response_length": len(response_message) if response_message else 0,
                "request_id": request_id,
            },
        )
        return ResponseBuilder.wrap_non_json(response_message, agent_config)
