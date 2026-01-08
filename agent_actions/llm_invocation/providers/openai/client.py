"""
OpenAI client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for OpenAI API integration, supporting GPT models.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import json
import logging
from datetime import datetime
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union
from openai import OpenAI
import openai
from openai.types.chat import ChatCompletionUserMessageParam, ChatCompletionSystemMessageParam
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.client_base import BaseClient
from agent_actions.llm_invocation.providers.usage_tracker import set_last_usage
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import RateLimitError, NetworkError, VendorAPIError

logger = logging.getLogger(__name__)


def _wrap_openai_error(e: Exception, model_name: str) -> Exception:
    """Wrap OpenAI SDK errors into unified agent-actions error types.

    This enables the central retry engine to handle transient errors
    consistently across all providers.

    Args:
        e: The OpenAI SDK exception
        model_name: Model name for context

    Returns:
        Wrapped exception (RateLimitError, NetworkError, or VendorAPIError)
    """
    context = {"vendor": "openai", "model": model_name}

    # Rate limit errors
    if isinstance(e, openai.RateLimitError):
        # Extract retry_after if available
        retry_after = None
        if hasattr(e, "response") and e.response:
            retry_after = e.response.headers.get("retry-after")
            if retry_after:
                try:
                    retry_after = float(retry_after)
                except ValueError:
                    retry_after = None
        context["retry_after"] = retry_after
        return RateLimitError(f"OpenAI rate limit: {e}", context=context, cause=e)

    # Connection/network errors
    if isinstance(e, openai.APIConnectionError):
        return NetworkError(f"OpenAI connection error: {e}", context=context, cause=e)

    # Timeout errors
    if isinstance(e, openai.APITimeoutError):
        return NetworkError(f"OpenAI timeout: {e}", context=context, cause=e)

    # Internal server errors (potentially transient)
    if isinstance(e, openai.InternalServerError):
        return NetworkError(f"OpenAI server error: {e}", context=context, cause=e)

    # Other API errors (not retryable)
    if isinstance(e, openai.APIError):
        return VendorAPIError(f"OpenAI API error: {e}", context=context, cause=e)

    # Unknown error, re-raise as-is
    return e


class OpenAIClient(BaseClient):
    """OpenAI API client for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(
        api_key: Optional[str],
        agent_config: Dict[str, Any],
        prompt_config: Dict[str, Any],
        context_data: Dict[str, Any],
        schema: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        client = OpenAI(api_key=api_key)
        model_name: str = agent_config[MODEL_NAME_KEY]
        context_data_str: str = StringProcessor.process_as_string(context_data)
        prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            RULES: ALWAYS READ INPUT AS STRING\n        "
        messages: List[ChatCompletionSystemMessageParam] = [
            {"role": "system", "content": dedent(prompt)}
        ]

        # Log API request at DEBUG level
        logger.debug(
            "OpenAI API request",
            extra={
                "operation": "openai_api_request",
                "model": model_name,
                "mode": "json",
                "message_count": len(messages),
                "has_schema": schema is not None,
            },
        )

        start_time = datetime.now()
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": schema},
            )
        except openai.APIError as e:
            raise _wrap_openai_error(e, model_name) from e
        duration = (datetime.now() - start_time).total_seconds()

        # Extract token usage and store in thread-local
        usage_data = None
        if response.usage:
            usage_data = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            set_last_usage(usage_data)

        # Log API response at DEBUG level
        logger.debug(
            "OpenAI API response",
            extra={
                "operation": "openai_api_response",
                "model": model_name,
                "duration": duration,
                "finish_reason": response.choices[0].finish_reason if response.choices else None,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else None,
                    "completion_tokens": (
                        response.usage.completion_tokens if response.usage else None
                    ),
                    "total_tokens": response.usage.total_tokens if response.usage else None,
                },
            },
        )
        response_message = response.choices[0].message
        response_content: Optional[str] = response_message.content
        if response_content is None:
            from agent_actions.errors import VendorAPIError  # New modular pattern!

            raise VendorAPIError(
                "Empty response content from OpenAI API",
                context={
                    "model_name": model_name,
                    "vendor": "openai",
                    "api_operation": "chat.completions.create",
                },
            )
        response_data: Union[Dict[str, Any], List[Dict[str, Any]]] = json.loads(response_content)
        response_list: List[Dict[str, Any]] = (
            response_data if isinstance(response_data, list) else [response_data]
        )
        return response_list

    @staticmethod
    def call_non_json(
        api_key: Optional[str],
        agent_config: Dict[str, Any],
        prompt_config: Dict[str, Any],
        context_data: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        client = OpenAI(api_key=api_key)
        model_name: str = agent_config[MODEL_NAME_KEY]
        context_data_str: str = StringProcessor.process_as_string(context_data)
        prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
        messages: List[ChatCompletionUserMessageParam] = [
            {"role": "user", "content": dedent(prompt)}
        ]

        # Log API request at DEBUG level
        logger.debug(
            "OpenAI API request",
            extra={
                "operation": "openai_api_request",
                "model": model_name,
                "mode": "non_json",
                "message_count": len(messages),
            },
        )

        start_time = datetime.now()
        try:
            response = client.chat.completions.create(model=model_name, messages=messages)
        except openai.APIError as e:
            raise _wrap_openai_error(e, model_name) from e
        duration = (datetime.now() - start_time).total_seconds()

        # Extract token usage and store in thread-local
        usage_data = None
        if response.usage:
            usage_data = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            set_last_usage(usage_data)

        # Log API response at DEBUG level
        logger.debug(
            "OpenAI API response",
            extra={
                "operation": "openai_api_response",
                "model": model_name,
                "duration": duration,
                "finish_reason": response.choices[0].finish_reason if response.choices else None,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else None,
                    "completion_tokens": (
                        response.usage.completion_tokens if response.usage else None
                    ),
                    "total_tokens": response.usage.total_tokens if response.usage else None,
                },
            },
        )
        response_message = response.choices[0].message
        output_field: str = agent_config.get("output_field", "raw_response")
        content: Optional[str] = response_message.content
        if content is None:
            raise VendorAPIError(
                "Empty response content from OpenAI API",
                context={
                    "model_name": model_name,
                    "vendor": "openai",
                    "api_operation": "chat.completions.create",
                    "output_field": output_field,
                },
            )
        response_content: Dict[str, str] = {output_field: content}
        return [response_content]
