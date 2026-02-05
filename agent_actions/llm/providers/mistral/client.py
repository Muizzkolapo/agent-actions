"""
Mistral client for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for Mistral API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import uuid
from datetime import datetime
from textwrap import dedent

from mistralai import Mistral
from mistralai import models as mistral_models

from agent_actions.input.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.mixins import (
    JSONResponseMixin,
    GenericErrorHandlerMixin,
)
from agent_actions.utils.constants import MODEL_NAME_KEY
from agent_actions.errors import VendorAPIError, RateLimitError, NetworkError
from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMRequestEvent,
    LLMResponseEvent,
    LLMErrorEvent,
)

logger = logging.getLogger(__name__)


_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="mistral",
    status_code_error_types=(mistral_models.SDKError,),
    extra_network_types=(ConnectionError, TimeoutError),
    supports_retry_after=False,
)


def _wrap_mistral_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Mistral SDK errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


class MistralClient(BaseClient, JSONResponseMixin, GenericErrorHandlerMixin):
    """Mistral AI API client for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="mistral",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            client = Mistral(api_key=api_key)
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            <|begin_of_output_schema|> : {schema} : <|end_of_output_schema|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            "
            prompt_dedent = dedent(prompt)
            messages = [{"role": "user", "content": prompt_dedent}]
            chat_response = client.chat.complete(
                model=model_name, response_format={"type": "json_object"}, messages=messages
            )
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except mistral_models.SDKError as e:
            raise _wrap_mistral_error(e, model_name, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="mistral",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            MistralClient.handle_generic_error(e, "Mistral", "call_json", model_name)

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        # Extract token usage
        prompt_tokens = chat_response.usage.prompt_tokens if chat_response.usage else 0
        completion_tokens = chat_response.usage.completion_tokens if chat_response.usage else 0
        total_tokens = chat_response.usage.total_tokens if chat_response.usage else 0

        if chat_response.usage:
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
                provider="mistral",
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        response_content = chat_response.choices[0].message.content

        return MistralClient.parse_json_response(
            response_content=response_content,
            vendor_name="Mistral",
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
                provider="mistral",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            client = Mistral(api_key=api_key)
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            "
            prompt_dedent = dedent(prompt)
            messages = [{"role": "user", "content": prompt_dedent}]
            chat_response = client.chat.complete(model=model_name, messages=messages)
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except mistral_models.SDKError as e:
            raise _wrap_mistral_error(e, model_name, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="mistral",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            logger.exception(
                "Mistral non-JSON API call failed",
                extra={
                    "operation": "mistral_call_non_json",
                    "model": model_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                },
            )
            raise VendorAPIError(
                f"Mistral non-JSON API call failed: {e}",
                vendor="mistral",
                operation="call_non_json",
                cause=e,
            ) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        # Extract token usage
        prompt_tokens = chat_response.usage.prompt_tokens if chat_response.usage else 0
        completion_tokens = chat_response.usage.completion_tokens if chat_response.usage else 0
        total_tokens = chat_response.usage.total_tokens if chat_response.usage else 0

        if chat_response.usage:
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
                provider="mistral",
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        response_output = chat_response.choices[0].message.content

        logger.debug(
            "Mistral non-JSON response retrieved successfully",
            extra={
                "operation": "mistral_call_non_json",
                "model": model_name,
                "response_length": len(response_output) if response_output else 0,
                "request_id": request_id,
            },
        )
        return [response_output]
