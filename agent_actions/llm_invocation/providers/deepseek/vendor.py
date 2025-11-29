import json
import logging
from openai import OpenAI
from agent_actions.preprocessing.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.shared.exceptions import VendorAPIError

logger = logging.getLogger(__name__)

class DeepSeekHandler(BaseVendorHandler):

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f'\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n\n            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT\n            RULES: RETURN JSON\n\n             "json_schema": {str(schema)} \n        '
            messages = [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': context_data_str}]
            response = client.chat.completions.create(model=model_name, messages=messages, response_format={'type': 'json_object'})
            response_message = response.choices[0].message
            response_content = response_message.content

            if not response_content:
                logger.error(
                    "DeepSeek returned empty response",
                    extra={
                        'operation': 'deepseek_call_json',
                        'model': model_name
                    }
                )
                raise VendorAPIError(
                    "DeepSeek returned empty response",
                    vendor="deepseek",
                    operation="call_json"
                )

            try:
                response_data = json.loads(response_content)
                logger.debug(
                    "DeepSeek JSON response parsed successfully",
                    extra={
                        'operation': 'deepseek_call_json',
                        'model': model_name,
                        'response_length': len(response_content)
                    }
                )
                return response_data
            except json.JSONDecodeError as e:
                logger.error(
                    "DeepSeek returned invalid JSON",
                    extra={
                        'operation': 'deepseek_call_json',
                        'model': model_name,
                        'response_text': response_content[:200],
                        'error': str(e),
                        'line': e.lineno if hasattr(e, 'lineno') else None
                    },
                    exc_info=True
                )
                raise VendorAPIError(
                    f"DeepSeek returned invalid JSON: {e}",
                    vendor="deepseek",
                    operation="call_json",
                    cause=e
                )
        except VendorAPIError:
            raise
        except Exception as e:
            logger.error(
                "DeepSeek API call failed",
                extra={
                    'operation': 'deepseek_call_json',
                    'model': model_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise VendorAPIError(
                f"DeepSeek API call failed: {e}",
                vendor="deepseek",
                operation="call_json",
                cause=e
            )

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        pass