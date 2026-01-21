"""
Cohere client for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for Cohere API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
from textwrap import dedent
import cohere
from cohere.core import api_error as cohere_errors
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.client_base import BaseClient
from agent_actions.llm_invocation.providers.mixins import (
    JSONResponseMixin,
    GenericErrorHandlerMixin,
)
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import VendorAPIError, RateLimitError, NetworkError
from agent_actions.llm_invocation.providers.usage_tracker import set_last_usage

logger = logging.getLogger(__name__)


def _wrap_cohere_error(e: Exception, model_name: str) -> Exception:
    """Wrap Cohere SDK errors into unified agent-actions error types.

    This enables the central retry engine to handle transient errors
    consistently across all providers.

    Args:
        e: The Cohere SDK exception
        model_name: Model name for context

    Returns:
        Wrapped exception (RateLimitError, NetworkError, or VendorAPIError)
    """
    context = {"vendor": "cohere", "model": model_name}

    # Check status code for rate limit (429)
    if isinstance(e, cohere_errors.ApiError):
        status_code = getattr(e, "status_code", None)
        if status_code == 429:
            return RateLimitError(f"Cohere rate limit: {e}", context=context, cause=e)
        if status_code in (502, 503, 504):
            return NetworkError(f"Cohere server error: {e}", context=context, cause=e)
        return VendorAPIError(f"Cohere API error: {e}", context=context, cause=e)

    # Connection errors
    if isinstance(e, (ConnectionError, TimeoutError)):
        return NetworkError(f"Cohere connection error: {e}", context=context, cause=e)

    # Unknown error, re-raise as-is
    return e


class CohereClient(BaseClient, JSONResponseMixin, GenericErrorHandlerMixin):
    """Cohere API client for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            context_data_str = StringProcessor.process_as_string(context_data)
            co = cohere.Client(api_key=api_key)
            prompt = f"""\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            <|begin_of_output_schema|> : GENERATE JSON with the fields {", ".join([f"'{field}'" for field in schema.keys()])} : <|end_of_output_schema|>\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            """
            prompt_dedent = dedent(prompt)
            response = co.chat(
                model=model_name, message=prompt_dedent, response_format={"type": "json_object"}
            )
            # Extract token usage (Cohere v1 uses meta.tokens)
            if hasattr(response, "meta") and response.meta and hasattr(response.meta, "tokens"):
                tokens = response.meta.tokens
                set_last_usage(
                    {
                        "input_tokens": tokens.input_tokens,
                        "output_tokens": tokens.output_tokens,
                        "total_tokens": tokens.input_tokens + tokens.output_tokens,
                    }
                )
            intermediate_json = response.text

            return CohereClient.parse_json_response(
                response_content=intermediate_json,
                vendor_name="Cohere",
                operation="call_json",
                model_name=model_name,
            )
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except cohere_errors.ApiError as e:
            raise _wrap_cohere_error(e, model_name) from e
        except Exception as e:
            CohereClient.handle_generic_error(e, "Cohere", "call_json", model_name)

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            co = cohere.ClientV2(api_key=api_key)
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        "
            messages = [{"role": "user", "content": dedent(prompt)}]
            response = co.chat(model=model_name, messages=messages)
            # Extract token usage (Cohere v2 uses usage.tokens)
            if hasattr(response, "usage") and response.usage and hasattr(response.usage, "tokens"):
                tokens = response.usage.tokens
                set_last_usage(
                    {
                        "input_tokens": tokens.input_tokens,
                        "output_tokens": tokens.output_tokens,
                        "total_tokens": tokens.input_tokens + tokens.output_tokens,
                    }
                )
            response_message = response.message.content[0].text

            logger.debug(
                "Cohere non-JSON response retrieved successfully",
                extra={
                    "operation": "cohere_call_non_json",
                    "model": model_name,
                    "response_length": len(response_message) if response_message else 0,
                },
            )
            return [response_message]
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except cohere_errors.ApiError as e:
            raise _wrap_cohere_error(e, model_name) from e
        except Exception as e:
            logger.exception(
                "Cohere non-JSON API call failed",
                extra={
                    "operation": "cohere_call_non_json",
                    "model": model_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise VendorAPIError(
                f"Cohere non-JSON API call failed: {e}",
                vendor="cohere",
                operation="call_non_json",
                cause=e,
            ) from e
