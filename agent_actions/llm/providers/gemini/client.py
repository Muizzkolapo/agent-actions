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
from textwrap import dedent
from typing import Any, ClassVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.input.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.llm.providers.mixins import (
    GenericErrorHandlerMixin,
    JSONResponseMixin,
)
from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
    LLMResponseEvent,
)
from agent_actions.output.response.config_fields import get_default
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
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n            <|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>\n\n            RULES: DO NOT ADD ANY KEY NOT IN PROVIDED SCHEMA LIST\n        "
            prompt_dedent = dedent(prompt)
            response_temp = client.models.generate_content(
                model=model_name, contents=prompt_dedent, config=config
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

        # Extract token usage (Gemini uses usage_metadata)
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        if hasattr(response_temp, "usage_metadata") and response_temp.usage_metadata:
            prompt_tokens = response_temp.usage_metadata.prompt_token_count or 0
            completion_tokens = response_temp.usage_metadata.candidates_token_count or 0
            total_tokens = response_temp.usage_metadata.total_token_count or 0
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
                provider="gemini",
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
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
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
            prompt_dedent = dedent(prompt)
            response_temp = client.models.generate_content(
                model=model_name, contents=prompt_dedent, config=config
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

        # Extract token usage (Gemini uses usage_metadata)
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        if hasattr(response_temp, "usage_metadata") and response_temp.usage_metadata:
            prompt_tokens = response_temp.usage_metadata.prompt_token_count or 0
            completion_tokens = response_temp.usage_metadata.candidates_token_count or 0
            total_tokens = response_temp.usage_metadata.total_token_count or 0
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
                provider="gemini",
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        output_field = agent_config.get("output_field", get_default("output_field"))
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
        return [{output_field: response_text}]
