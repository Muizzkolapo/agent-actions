"""
DeepSeek handler for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for DeepSeek API integration using OpenAI-compatible SDK.
"""

import logging
from openai import OpenAI  # pylint: disable=import-error
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.llm_invocation.providers.mixins import (
    JSONResponseMixin,
    GenericErrorHandlerMixin
)
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import VendorAPIError  # New modular pattern!

logger = logging.getLogger(__name__)


class DeepSeekHandler(BaseVendorHandler, JSONResponseMixin, GenericErrorHandlerMixin):
    """DeepSeek API handler for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f'\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            RULES: RETURN JSON\n\n             "json_schema": {str(schema)} \n        '
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": context_data_str},
            ]
            response = client.chat.completions.create(
                model=model_name, messages=messages, response_format={"type": "json_object"}
            )
            response_message = response.choices[0].message
            response_content = response_message.content

            return DeepSeekHandler.parse_json_response(
                response_content=response_content,
                vendor_name="DeepSeek",
                operation="call_json",
                model_name=model_name,
            )
        except VendorAPIError:
            raise
        except Exception as e:
            DeepSeekHandler.handle_generic_error(e, "DeepSeek", "call_json", model_name)

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        pass
