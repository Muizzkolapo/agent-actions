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

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from agent_actions.input.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.mixins import (
    JSONResponseMixin,
    GenericErrorHandlerMixin,
)
from agent_actions.utils.constants import MODEL_NAME_KEY
from agent_actions.errors import VendorAPIError, RateLimitError, NetworkError
from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMRequestEvent,
    LLMResponseEvent,
    LLMErrorEvent,
    RateLimitEvent,
)

logger = logging.getLogger(__name__)


def _wrap_gemini_error(
    e: Exception, model_name: str, request_id: str = ""
) -> Exception:
    """Wrap Google Gemini SDK errors into unified agent-actions error types.

    This enables the central retry engine to handle transient errors
    consistently across all providers. Also fires appropriate LLM events.

    Args:
        e: The Google API exception
        model_name: Model name for context
        request_id: Request ID for correlation

    Returns:
        Wrapped exception (RateLimitError, NetworkError, or VendorAPIError)
    """
    context = {"vendor": "gemini", "model": model_name}

    # Rate limit / quota exceeded
    if isinstance(e, google_exceptions.ResourceExhausted):
        fire_event(
            RateLimitEvent(
                provider="gemini",
                retry_after=0.0,
                request_id=request_id,
            )
        )
        return RateLimitError(f"Gemini rate limit: {e}", context=context, cause=e)

    # Service unavailable (potentially transient)
    if isinstance(e, google_exceptions.ServiceUnavailable):
        fire_event(
            LLMErrorEvent(
                provider="gemini",
                model=model_name,
                error_type="ServiceUnavailable",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return NetworkError(f"Gemini service unavailable: {e}", context=context, cause=e)

    # Timeout / deadline exceeded
    if isinstance(e, google_exceptions.DeadlineExceeded):
        fire_event(
            LLMErrorEvent(
                provider="gemini",
                model=model_name,
                error_type="DeadlineExceeded",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return NetworkError(f"Gemini timeout: {e}", context=context, cause=e)

    # Internal server error
    if isinstance(e, google_exceptions.InternalServerError):
        fire_event(
            LLMErrorEvent(
                provider="gemini",
                model=model_name,
                error_type="InternalServerError",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return NetworkError(f"Gemini server error: {e}", context=context, cause=e)

    # Other Google API errors (not retryable)
    if isinstance(e, google_exceptions.GoogleAPICallError):
        fire_event(
            LLMErrorEvent(
                provider="gemini",
                model=model_name,
                error_type="GoogleAPICallError",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return VendorAPIError(f"Gemini API error: {e}", context=context, cause=e)

    # Unknown error, re-raise as-is
    return e


class GeminiClient(BaseClient, JSONResponseMixin, GenericErrorHandlerMixin):
    """Google Gemini API client for JSON and non-JSON LLM invocations."""

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
            genai.configure(api_key=api_key)
            llm = genai.GenerativeModel(
                model_name,
                system_instruction="Return only JSON",
                generation_config={"response_mime_type": "application/json"},
            )
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n            <|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>\n\n            RULES: DO NOT ADD ANY KEY NOT IN PROVIDED SCHEMA LIST\n        "
            prompt_dedent = dedent(prompt)
            response_temp = llm.generate_content(prompt_dedent)
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except google_exceptions.GoogleAPICallError as e:
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
            prompt_tokens = response_temp.usage_metadata.prompt_token_count
            completion_tokens = response_temp.usage_metadata.candidates_token_count
            total_tokens = response_temp.usage_metadata.total_token_count
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

        return GeminiClient.parse_json_response(
            response_content=response_temp.text,
            vendor_name="Gemini",
            operation="call_json",
            model_name=model_name,
        )

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
            genai.configure(api_key=api_key)
            llm = genai.GenerativeModel(
                model_name,
                system_instruction="Return only JSON",
                generation_config={"response_mime_type": "application/json"},
            )
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
            prompt_dedent = dedent(prompt)
            response_temp = llm.generate_content(prompt_dedent)
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except google_exceptions.GoogleAPICallError as e:
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
                operation="call_non_json",
                cause=e,
            ) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        # Extract token usage (Gemini uses usage_metadata)
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        if hasattr(response_temp, "usage_metadata") and response_temp.usage_metadata:
            prompt_tokens = response_temp.usage_metadata.prompt_token_count
            completion_tokens = response_temp.usage_metadata.candidates_token_count
            total_tokens = response_temp.usage_metadata.total_token_count
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

        response_list = response_temp.text

        logger.debug(
            "Gemini non-JSON response retrieved successfully",
            extra={
                "operation": "gemini_call_non_json",
                "model": model_name,
                "response_length": len(response_list) if response_list else 0,
                "request_id": request_id,
            },
        )
        return [response_list]
