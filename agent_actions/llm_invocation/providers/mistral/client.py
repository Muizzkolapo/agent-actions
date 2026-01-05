"""
Mistral client for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for Mistral API integration.
"""

import logging
from textwrap import dedent
from mistralai import Mistral
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.client_base import BaseClient
from agent_actions.llm_invocation.providers.mixins import (
    JSONResponseMixin,
    GenericErrorHandlerMixin,
)
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import VendorAPIError  # New modular pattern!
from agent_actions.llm_invocation.providers.usage_tracker import set_last_usage

logger = logging.getLogger(__name__)


class MistralClient(BaseClient, JSONResponseMixin, GenericErrorHandlerMixin):
    """Mistral AI API client for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            client = Mistral(api_key=api_key)
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            <|begin_of_output_schema|> : {schema} : <|end_of_output_schema|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            "
            prompt_dedent = dedent(prompt)
            messages = [{"role": "user", "content": prompt_dedent}]
            chat_response = client.chat.complete(
                model=model_name, response_format={"type": "json_object"}, messages=messages
            )
            # Extract token usage
            if chat_response.usage:
                set_last_usage(
                    {
                        "input_tokens": chat_response.usage.prompt_tokens,
                        "output_tokens": chat_response.usage.completion_tokens,
                        "total_tokens": chat_response.usage.total_tokens,
                    }
                )
            response_content = chat_response.choices[0].message.content

            return MistralClient.parse_json_response(
                response_content=response_content,
                vendor_name="Mistral",
                operation="call_json",
                model_name=model_name,
            )
        except VendorAPIError:
            raise
        except Exception as e:
            MistralClient.handle_generic_error(e, "Mistral", "call_json", model_name)

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            client = Mistral(api_key=api_key)
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f"\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            "
            prompt_dedent = dedent(prompt)
            messages = [{"role": "user", "content": prompt_dedent}]
            chat_response = client.chat.complete(model=model_name, messages=messages)
            # Extract token usage
            if chat_response.usage:
                set_last_usage(
                    {
                        "input_tokens": chat_response.usage.prompt_tokens,
                        "output_tokens": chat_response.usage.completion_tokens,
                        "total_tokens": chat_response.usage.total_tokens,
                    }
                )
            response_output = chat_response.choices[0].message.content

            logger.debug(
                "Mistral non-JSON response retrieved successfully",
                extra={
                    "operation": "mistral_call_non_json",
                    "model": model_name,
                    "response_length": len(response_output) if response_output else 0,
                },
            )
            return [response_output]
        except Exception as e:
            logger.exception(
                "Mistral non-JSON API call failed",
                extra={
                    "operation": "mistral_call_non_json",
                    "model": model_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise VendorAPIError(
                f"Mistral non-JSON API call failed: {e}",
                vendor="mistral",
                operation="call_non_json",
                cause=e,
            ) from e
