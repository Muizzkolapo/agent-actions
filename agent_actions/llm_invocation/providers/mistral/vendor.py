import json
import logging
from mistralai import Mistral
from agent_actions.preprocessing.string_transformer import StringProcessor
from textwrap import dedent
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import VendorAPIError  # New modular pattern!

logger = logging.getLogger(__name__)

class MistralHandler(BaseVendorHandler):

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            client = Mistral(api_key=api_key)
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f'\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            <|begin_of_output_schema|> : {schema} : <|end_of_output_schema|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            '
            prompt_dedent = dedent(prompt)
            messages = [{'role': 'user', 'content': prompt_dedent}]
            chat_response = client.chat.complete(model=model_name, response_format={'type': 'json_object'}, messages=messages)
            response_content = chat_response.choices[0].message.content

            if not response_content:
                logger.error(
                    "Mistral returned empty response",
                    extra={
                        'operation': 'mistral_call_json',
                        'model': model_name
                    }
                )
                raise VendorAPIError(
                    "Mistral returned empty response",
                    vendor="mistral",
                    operation="call_json"
                )

            try:
                data = json.loads(response_content)
                logger.debug(
                    "Mistral JSON response parsed successfully",
                    extra={
                        'operation': 'mistral_call_json',
                        'model': model_name,
                        'response_length': len(response_content)
                    }
                )
                return data
            except json.JSONDecodeError as e:
                logger.error(
                    "Mistral returned invalid JSON",
                    extra={
                        'operation': 'mistral_call_json',
                        'model': model_name,
                        'response_text': response_content[:200],
                        'error': str(e),
                        'line': e.lineno if hasattr(e, 'lineno') else None
                    },
                    exc_info=True
                )
                raise VendorAPIError(
                    f"Mistral returned invalid JSON: {e}",
                    vendor="mistral",
                    operation="call_json",
                    cause=e
                )
        except VendorAPIError:
            raise
        except Exception as e:
            logger.error(
                "Mistral API call failed",
                extra={
                    'operation': 'mistral_call_json',
                    'model': model_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise VendorAPIError(
                f"Mistral API call failed: {e}",
                vendor="mistral",
                operation="call_json",
                cause=e
            )

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            client = Mistral(api_key=api_key)
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f'\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            '
            prompt_dedent = dedent(prompt)
            messages = [{'role': 'user', 'content': prompt_dedent}]
            chat_response = client.chat.complete(model=model_name, messages=messages)
            response_output = chat_response.choices[0].message.content

            logger.debug(
                "Mistral non-JSON response retrieved successfully",
                extra={
                    'operation': 'mistral_call_non_json',
                    'model': model_name,
                    'response_length': len(response_output) if response_output else 0
                }
            )
            return [response_output]
        except Exception as e:
            logger.error(
                "Mistral non-JSON API call failed",
                extra={
                    'operation': 'mistral_call_non_json',
                    'model': model_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise VendorAPIError(
                f"Mistral non-JSON API call failed: {e}",
                vendor="mistral",
                operation="call_non_json",
                cause=e
            )