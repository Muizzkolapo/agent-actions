import cohere
import json
import logging
from textwrap import dedent
from agent_actions.preprocessing.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.shared.exceptions import VendorAPIError

logger = logging.getLogger(__name__)

class CohereHandler(BaseVendorHandler):

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            context_data_str = StringProcessor.process_as_string(context_data)
            co = cohere.Client(api_key=api_key)
            prompt = f"""\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {context_data_str} :<|end_of_text|>\n            <|begin_of_output_schema|> : GENERATE JSON with the fields {', '.join([f"'{field}'" for field in schema.keys()])} : <|end_of_output_schema|>\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            """
            prompt_dedent = dedent(prompt)
            response = co.chat(model=model_name, message=prompt_dedent, response_format={'type': 'json_object'})
            intermediate_json = response.text

            if not intermediate_json:
                logger.error(
                    "Cohere returned empty response",
                    extra={
                        'operation': 'cohere_call_json',
                        'model': model_name
                    }
                )
                raise VendorAPIError(
                    "Cohere returned empty response",
                    vendor="cohere",
                    operation="call_json"
                )

            try:
                final_data = json.loads(intermediate_json)
                logger.debug(
                    "Cohere JSON response parsed successfully",
                    extra={
                        'operation': 'cohere_call_json',
                        'model': model_name,
                        'response_length': len(intermediate_json)
                    }
                )
                return final_data
            except json.JSONDecodeError as e:
                logger.error(
                    "Cohere returned invalid JSON",
                    extra={
                        'operation': 'cohere_call_json',
                        'model': model_name,
                        'response_text': intermediate_json[:200],
                        'error': str(e),
                        'line': e.lineno if hasattr(e, 'lineno') else None
                    },
                    exc_info=True
                )
                raise VendorAPIError(
                    f"Cohere returned invalid JSON: {e}",
                    vendor="cohere",
                    operation="call_json",
                    cause=e
                )
        except VendorAPIError:
            raise
        except Exception as e:
            logger.error(
                "Cohere API call failed",
                extra={
                    'operation': 'cohere_call_json',
                    'model': model_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise VendorAPIError(
                f"Cohere API call failed: {e}",
                vendor="cohere",
                operation="call_json",
                cause=e
            )

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            co = cohere.ClientV2(api_key=api_key)
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f'\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        '
            messages = [{'role': 'user', 'content': dedent(prompt)}]
            response = co.chat(model=model_name, messages=messages)
            response_message = response.message.content[0].text

            logger.debug(
                "Cohere non-JSON response retrieved successfully",
                extra={
                    'operation': 'cohere_call_non_json',
                    'model': model_name,
                    'response_length': len(response_message) if response_message else 0
                }
            )
            return [response_message]
        except Exception as e:
            logger.error(
                "Cohere non-JSON API call failed",
                extra={
                    'operation': 'cohere_call_non_json',
                    'model': model_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise VendorAPIError(
                f"Cohere non-JSON API call failed: {e}",
                vendor="cohere",
                operation="call_non_json",
                cause=e
            )