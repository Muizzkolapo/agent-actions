"""
Anthropic Claude client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for Anthropic's Claude API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
from datetime import datetime
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union

import anthropic

from agent_actions.llm_invocation.providers.usage_tracker import set_last_usage
from agent_actions.llm_invocation.providers.client_base import BaseClient
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import RateLimitError, NetworkError, VendorAPIError, ConfigurationError

logger = logging.getLogger(__name__)


def _wrap_anthropic_error(e: Exception, model_name: str) -> Exception:
    """Wrap Anthropic SDK errors into unified agent-actions error types.

    This enables the central retry engine to handle transient errors
    consistently across all providers.

    Args:
        e: The Anthropic SDK exception
        model_name: Model name for context

    Returns:
        Wrapped exception (RateLimitError, NetworkError, or VendorAPIError)
    """
    context = {"vendor": "anthropic", "model": model_name}

    # Rate limit errors
    if isinstance(e, anthropic.RateLimitError):
        retry_after = None
        if hasattr(e, "response") and e.response:
            retry_after = e.response.headers.get("retry-after")
            if retry_after:
                try:
                    retry_after = float(retry_after)
                except ValueError:
                    retry_after = None
        context["retry_after"] = retry_after
        return RateLimitError(f"Anthropic rate limit: {e}", context=context, cause=e)

    # Connection/network errors
    if isinstance(e, anthropic.APIConnectionError):
        return NetworkError(f"Anthropic connection error: {e}", context=context, cause=e)

    # Timeout errors
    if isinstance(e, anthropic.APITimeoutError):
        return NetworkError(f"Anthropic timeout: {e}", context=context, cause=e)

    # Internal server errors (potentially transient)
    if isinstance(e, anthropic.InternalServerError):
        return NetworkError(f"Anthropic server error: {e}", context=context, cause=e)

    # Other API errors (not retryable)
    if isinstance(e, anthropic.APIError):
        return VendorAPIError(f"Anthropic API error: {e}", context=context, cause=e)

    # Unknown error, re-raise as-is
    return e


class AnthropicClient(BaseClient):
    """Anthropic Claude API client for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(
        api_key: Optional[str],
        agent_config: Dict[str, Any],
        prompt_config: Dict[str, Any],
        context_data: Dict[str, Any],
        schema: Optional[Dict[str, Any]],
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        model_name: str = agent_config[MODEL_NAME_KEY]
        client = anthropic.Anthropic(api_key=api_key)
        context_data_str: str = StringProcessor.process_as_string(context_data)
        prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
        prompt_dedent: str = dedent(prompt)
        api_args = {
            "model": model_name,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt_dedent}],
        }
        if schema is not None:
            api_args["tools"] = schema

        # Log API request at DEBUG level
        logger.debug(
            "Anthropic API request",
            extra={
                "operation": "anthropic_api_request",
                "model": model_name,
                "mode": "json",
                "max_tokens": 1024,
                "has_tools": schema is not None,
            },
        )

        start_time = datetime.now()
        try:
            response = client.messages.create(**api_args)
        except anthropic.APIError as e:
            raise _wrap_anthropic_error(e, model_name) from e
        duration = (datetime.now() - start_time).total_seconds()

        # Extract token usage and store in thread-local
        usage_data = None
        if response.usage:
            usage_data = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }
            set_last_usage(usage_data)

        # Log API response at DEBUG level
        logger.debug(
            "Anthropic API response",
            extra={
                "operation": "anthropic_api_response",
                "model": model_name,
                "duration": duration,
                "stop_reason": response.stop_reason,
                "usage": {
                    "input_tokens": response.usage.input_tokens if response.usage else None,
                    "output_tokens": response.usage.output_tokens if response.usage else None,
                },
            },
        )
        response_content: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = next(
            (block.input for block in response.content if hasattr(block, "input")), None
        )
        if response_content is None:
            text_content = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "No text content available",
            )
            raise VendorAPIError(
                "No valid content with 'input' found in response",
                context={
                    "model_name": model_name,
                    "vendor": "anthropic",
                    "text_content": text_content[:200],
                    "api_operation": "messages.create",
                },
            )
        return response_content

    @staticmethod
    def call_non_json(
        api_key: Optional[str],
        agent_config: Dict[str, Any],
        prompt_config: Dict[str, Any],
        context_data: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        """Non-JSON mode is not implemented for Claude."""
        raise ConfigurationError(
            "Non-JSON mode not implemented for Claude",
            context={
                "vendor": "anthropic",
                "supported_modes": ["json"],
                "model_name": agent_config.get(MODEL_NAME_KEY),
            },
        )
