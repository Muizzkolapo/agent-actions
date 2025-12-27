"""
Gemini handler for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for Google Gemini API integration.
"""

import logging
from textwrap import dedent
import google.generativeai as genai  # pylint: disable=import-error
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.llm_invocation.providers.mixins import (
    JSONResponseMixin,
    GenericErrorHandlerMixin,
)
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import VendorAPIError  # New modular pattern!
from agent_actions.llm_invocation.providers.usage_tracker import set_last_usage

logger = logging.getLogger(__name__)


class GeminiHandler(BaseVendorHandler, JSONResponseMixin, GenericErrorHandlerMixin):
    """Google Gemini API handler for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
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
            # Extract token usage (Gemini uses usage_metadata)
            if hasattr(response_temp, "usage_metadata") and response_temp.usage_metadata:
                set_last_usage(
                    {
                        "input_tokens": response_temp.usage_metadata.prompt_token_count,
                        "output_tokens": response_temp.usage_metadata.candidates_token_count,
                        "total_tokens": response_temp.usage_metadata.total_token_count,
                    }
                )

            return GeminiHandler.parse_json_response(
                response_content=response_temp.text,
                vendor_name="Gemini",
                operation="call_json",
                model_name=model_name,
            )
        except VendorAPIError:
            raise
        except Exception as e:
            GeminiHandler.handle_generic_error(e, "Gemini", "call_json", model_name)

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]
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
            # Extract token usage (Gemini uses usage_metadata)
            if hasattr(response_temp, "usage_metadata") and response_temp.usage_metadata:
                set_last_usage(
                    {
                        "input_tokens": response_temp.usage_metadata.prompt_token_count,
                        "output_tokens": response_temp.usage_metadata.candidates_token_count,
                        "total_tokens": response_temp.usage_metadata.total_token_count,
                    }
                )
            response_list = response_temp.text

            logger.debug(
                "Gemini non-JSON response retrieved successfully",
                extra={
                    "operation": "gemini_call_non_json",
                    "model": model_name,
                    "response_length": len(response_list) if response_list else 0,
                },
            )
            return [response_list]
        except Exception as e:
            logger.exception(
                "Gemini non-JSON API call failed",
                extra={
                    "operation": "gemini_call_non_json",
                    "model": model_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise VendorAPIError(
                f"Gemini non-JSON API call failed: {e}",
                vendor="gemini",
                operation="call_non_json",
                cause=e,
            ) from e
