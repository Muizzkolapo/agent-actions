"""
Anthropic Claude client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for Anthropic's Claude API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import uuid
from datetime import datetime
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union

import anthropic

from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.input.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.utils.constants import MODEL_NAME_KEY
from agent_actions.errors import RateLimitError, NetworkError, VendorAPIError, ConfigurationError
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
    LLMResponseEvent,
)

logger = logging.getLogger(__name__)

_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="anthropic",
    rate_limit_types=(anthropic.RateLimitError,),
    network_error_types=(
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.InternalServerError,
    ),
    base_api_error_type=anthropic.APIError,
    supports_retry_after=True,
)


def _wrap_anthropic_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Anthropic SDK errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


class AnthropicClient(BaseClient):
    """Anthropic Claude API client for JSON and non-JSON LLM invocations."""

    @staticmethod
    def _build_api_args(
        model_name: str,
        prompt_dedent: str,
        schema: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build API arguments for the Anthropic call."""
        api_args = {
            "model": model_name,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt_dedent}],
        }
        if schema is not None:
            api_args["tools"] = schema
        return api_args

    @staticmethod
    def _extract_and_store_usage(response: Any) -> None:
        """Extract token usage from response and store in thread-local."""
        if not response.usage:
            return
        usage_data = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }
        set_last_usage(usage_data)

    @staticmethod
    def _extract_response_content(
        response: Any, model_name: str
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Extract content from response, raising error if not found."""
        response_content = next(
            (block.input for block in response.content if hasattr(block, "input")), None
        )
        if response_content is not None:
            return response_content

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

        api_args = AnthropicClient._build_api_args(model_name, prompt_dedent, schema)

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        logger.debug(
            "Anthropic API request",
            extra={
                "operation": "anthropic_api_request",
                "model": model_name,
                "mode": "json",
                "max_tokens": 1024,
                "has_tools": schema is not None,
                "request_id": request_id,
            },
        )

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="anthropic",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            response = client.messages.create(**api_args)
        except anthropic.APIError as e:
            raise _wrap_anthropic_error(e, model_name, request_id) from e
        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        # Extract token usage
        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0
        total_tokens = input_tokens + output_tokens

        AnthropicClient._extract_and_store_usage(response)

        # Fire LLM response event
        fire_event(
            LLMResponseEvent(
                provider="anthropic",
                model=model_name,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        logger.debug(
            "Anthropic API response",
            extra={
                "operation": "anthropic_api_response",
                "model": model_name,
                "duration": duration,
                "stop_reason": response.stop_reason,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                "request_id": request_id,
            },
        )

        try:
            return AnthropicClient._extract_response_content(response, model_name)
        except VendorAPIError as e:
            fire_event(
                LLMErrorEvent(
                    provider="anthropic",
                    model=model_name,
                    error_type="ContentExtractionError",
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            raise

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
