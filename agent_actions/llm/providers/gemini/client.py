"""
Gemini client for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for Google Gemini API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, ClassVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
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
    vendor_name="gemini",
    status_code_error_types=(genai_errors.ClientError, genai_errors.ServerError),
    base_api_error_type=genai_errors.APIError,
    supports_retry_after=False,
)


def _wrap_gemini_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Google Gemini SDK errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


def _build_client(api_key: str) -> genai.Client:
    """Build a google-genai Client instance."""
    return genai.Client(api_key=api_key)


class GeminiClient(BaseClient, JSONResponseMixin, GenericErrorHandlerMixin):
    """Google Gemini API client for JSON and non-JSON LLM invocations."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    }

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="gemini",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            client = _build_client(api_key)
            gen_params = extract_generation_params(
                agent_config,
                key_map={"max_tokens": "max_output_tokens", "stop": "stop_sequences"},
                stop_as_list=True,
            )
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                **gen_params,
            )
            envelope = MessageBuilder.build(
                "gemini", prompt_config, context_data, schema=schema, json_mode=True
            )
            response_temp = client.models.generate_content(
                model=model_name, contents=envelope.prompt_body, config=config
            )
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except genai_errors.APIError as e:
            raise _wrap_gemini_error(e, model_name, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="gemini",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            GeminiClient.handle_generic_error(e, "Gemini", "call_json", model_name)

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            response_temp, "gemini", model_name, latency_ms, request_id
        )

        result = GeminiClient.parse_json_response(
            response_content=response_temp.text or "",
            vendor_name="Gemini",
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
                provider="gemini",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            client = _build_client(api_key)
            gen_params = extract_generation_params(
                agent_config,
                key_map={"max_tokens": "max_output_tokens", "stop": "stop_sequences"},
                stop_as_list=True,
            )
            config = types.GenerateContentConfig(**gen_params) if gen_params else None
            envelope = MessageBuilder.build("gemini", prompt_config, context_data, json_mode=False)
            response_temp = client.models.generate_content(
                model=model_name, contents=envelope.prompt_body, config=config
            )
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except genai_errors.APIError as e:
            raise _wrap_gemini_error(e, model_name, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="gemini",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            logger.exception(
                "Gemini non-JSON API call failed",
                extra={
                    "operation": "gemini_call_non_json",
                    "model": model_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                },
            )
            raise VendorAPIError(
                f"Gemini non-JSON API call failed: {e}",
                vendor="gemini",
                cause=e,
            ) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            response_temp, "gemini", model_name, latency_ms, request_id
        )

        response_text = response_temp.text or ""

        logger.debug(
            "Gemini non-JSON response retrieved successfully",
            extra={
                "operation": "gemini_call_non_json",
                "model": model_name,
                "response_length": len(response_text) if response_text else 0,
                "request_id": request_id,
            },
        )
        return ResponseBuilder.wrap_non_json(response_text, agent_config)
