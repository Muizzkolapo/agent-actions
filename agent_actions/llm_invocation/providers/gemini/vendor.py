import json
import logging
from textwrap import dedent
import google.generativeai as genai
from agent_actions.preprocessing.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import VendorAPIError  # New modular pattern!

logger = logging.getLogger(__name__)

class GeminiHandler(BaseVendorHandler):

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            genai.configure(api_key=api_key)
            llm = genai.GenerativeModel(model_name, system_instruction='Return only JSON', generation_config={'response_mime_type': 'application/json'})
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f'\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n            <|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>\n\n            RULES: DO NOT ADD ANY KEY NOT IN PROVIDED SCHEMA LIST\n        '
            prompt_dedent = dedent(prompt)
            response_temp = llm.generate_content(prompt_dedent)

            try:
                response = json.loads(response_temp.text)
                logger.debug(
                    "Gemini JSON response parsed successfully",
                    extra={
                        'operation': 'gemini_call_json',
                        'model': model_name,
                        'response_length': len(response_temp.text)
                    }
                )
                return response
            except json.JSONDecodeError as e:
                logger.error(
                    "Gemini returned invalid JSON",
                    extra={
                        'operation': 'gemini_call_json',
                        'model': model_name,
                        'response_text': response_temp.text[:200] if response_temp.text else 'None',
                        'error': str(e),
                        'line': e.lineno if hasattr(e, 'lineno') else None
                    },
                    exc_info=True
                )
                raise VendorAPIError(
                    f"Gemini returned invalid JSON: {e}",
                    vendor="gemini",
                    operation="call_json",
                    cause=e
                )
        except VendorAPIError:
            raise
        except Exception as e:
            logger.error(
                "Gemini API call failed",
                extra={
                    'operation': 'gemini_call_json',
                    'model': model_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise VendorAPIError(
                f"Gemini API call failed: {e}",
                vendor="gemini",
                operation="call_json",
                cause=e
            )

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]
        try:
            genai.configure(api_key=api_key)
            llm = genai.GenerativeModel(model_name, system_instruction='Return only JSON', generation_config={'response_mime_type': 'application/json'})
            context_data_str = StringProcessor.process_as_string(context_data)
            prompt = f'\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        '
            prompt_dedent = dedent(prompt)
            response_temp = llm.generate_content(prompt_dedent)
            response_list = response_temp.text

            logger.debug(
                "Gemini non-JSON response retrieved successfully",
                extra={
                    'operation': 'gemini_call_non_json',
                    'model': model_name,
                    'response_length': len(response_list) if response_list else 0
                }
            )
            return [response_list]
        except Exception as e:
            logger.error(
                "Gemini non-JSON API call failed",
                extra={
                    'operation': 'gemini_call_non_json',
                    'model': model_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            raise VendorAPIError(
                f"Gemini non-JSON API call failed: {e}",
                vendor="gemini",
                operation="call_non_json",
                cause=e
            )