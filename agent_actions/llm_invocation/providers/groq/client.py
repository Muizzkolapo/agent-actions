"""
Groq LLM client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for Groq API integration, supporting models like Llama3.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.

JSON parse failures return error dicts for RepromptEngine repair support,
as Groq's json_object mode can produce malformed output.
"""

import json
import logging
from textwrap import dedent

import groq
from groq import Groq

logger = logging.getLogger(__name__)

from agent_actions.errors import VendorAPIError, RateLimitError, NetworkError
from agent_actions.llm_invocation.providers.client_base import BaseClient
from agent_actions.llm_invocation.providers.usage_tracker import set_last_usage
from agent_actions.preprocessing.transformation.data_transformer import DataTransformer
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.utilities.constants import MODEL_NAME_KEY


def _wrap_groq_error(e: Exception, model_name: str) -> Exception:
    """Wrap Groq SDK errors into unified agent-actions error types.

    Groq uses an OpenAI-compatible SDK, so error types are similar.

    Args:
        e: The Groq SDK exception
        model_name: Model name for context

    Returns:
        Wrapped exception (RateLimitError, NetworkError, or VendorAPIError)
    """
    context = {"vendor": "groq", "model": model_name}

    # Rate limit errors
    if isinstance(e, groq.RateLimitError):
        retry_after = None
        if hasattr(e, "response") and e.response:
            retry_after = e.response.headers.get("retry-after")
            if retry_after:
                try:
                    retry_after = float(retry_after)
                except ValueError:
                    retry_after = None
        context["retry_after"] = retry_after
        return RateLimitError(f"Groq rate limit: {e}", context=context, cause=e)

    # Connection/network errors
    if isinstance(e, groq.APIConnectionError):
        return NetworkError(f"Groq connection error: {e}", context=context, cause=e)

    # Timeout errors
    if isinstance(e, groq.APITimeoutError):
        return NetworkError(f"Groq timeout: {e}", context=context, cause=e)

    # Internal server errors (potentially transient)
    if isinstance(e, groq.InternalServerError):
        return NetworkError(f"Groq server error: {e}", context=context, cause=e)

    # Other API errors (not retryable)
    if isinstance(e, groq.APIError):
        return VendorAPIError(f"Groq API error: {e}", context=context, cause=e)

    # Unknown error, re-raise as-is
    return e


class GroqClient(BaseClient):
    """Groq API client for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        client = Groq(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"\n            <|begin_of_user_instruction|>:{prompt_config} :<|end_of_user_instruction|>\n\n            <|begin_of_text|>:: {context_data_str} :<|end_of_text|>\n\n            <|begin_of_output_schema|> :WRITE OUTPUTS IN JSON SCHEMA: {json.dumps(schema)}. : <|end_of_output_schema|>\n        "
        prompt_dedent = dedent(prompt)
        try:
            llm = client.chat.completions.create(
                messages=[{"role": "system", "content": prompt_dedent}],
                model=model_name,
                response_format={"type": "json_object"},
            )
            # Extract token usage (OpenAI-compatible format)
            if llm.usage:
                set_last_usage(
                    {
                        "input_tokens": llm.usage.prompt_tokens,
                        "output_tokens": llm.usage.completion_tokens,
                        "total_tokens": llm.usage.total_tokens,
                    }
                )
            response_temp = llm.choices[0].message.content
            try:
                response = json.loads(response_temp)
                response_list = DataTransformer.ensure_list(response)
                return response_list
            except json.JSONDecodeError as e:
                # Return error dict for RepromptEngine repair
                logger.warning(
                    "Groq returned invalid JSON, returning error dict for repair",
                    extra={
                        "model": model_name,
                        "response_text": response_temp[:200] if response_temp else "",
                        "error": str(e),
                    },
                )
                return [{"raw_response": response_temp, "_parse_error": str(e)}]
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except groq.APIError as e:
            raise _wrap_groq_error(e, model_name) from e
        except Exception as e:
            raise VendorAPIError(
                "Failed to create chat completion with Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "api_operation": "chat.completions.create",
                },
                cause=e,
            ) from e

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        client = Groq(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"\n                Instructions: {prompt_config}\n                Input Text: {str(context_data_str)}\n                \n                Please provide a direct response without any JSON formatting.\n                Begin your response here:\n            "
        prompt_dedent = dedent(prompt).strip()
        completion_kwargs = {
            "messages": [{"role": "system", "content": prompt_dedent}],
            "model": model_name,
            "temperature": 0.7,
            "max_tokens": 1000,
        }
        try:
            response = client.chat.completions.create(**completion_kwargs)
        except groq.APIError as e:
            raise _wrap_groq_error(e, model_name) from e
        # Extract token usage (OpenAI-compatible format)
        if response.usage:
            set_last_usage(
                {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            )
        try:
            response_content = response.choices[0].message.content
            return [response_content]
        except (AttributeError, IndexError, TypeError) as e:
            raise VendorAPIError(
                "Error parsing non-JSON response from Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "response": str(response)[:200],
                },
                cause=e,
            )
        except Exception as e:
            raise VendorAPIError(
                "Failed to get non-JSON chat completion from Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "api_operation": "chat.completions.create",
                },
                cause=e,
            ) from e
