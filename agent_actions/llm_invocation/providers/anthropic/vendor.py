import anthropic
import logging
from datetime import datetime
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union
from agent_actions.preprocessing.string_transformer import StringProcessor
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.utilities.constants import MODEL_NAME_KEY

logger = logging.getLogger(__name__)

class ClaudeHandler(BaseVendorHandler):

    @staticmethod
    def call_json(api_key: Optional[str], agent_config: Dict[str, Any], prompt_config: Dict[str, Any], context_data: Dict[str, Any], schema: Optional[Dict[str, Any]]) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        model_name: str = agent_config[MODEL_NAME_KEY]
        client = anthropic.Anthropic(api_key=api_key)
        context_data_str: str = StringProcessor.process_as_string(context_data)
        prompt = f'\n            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>\n            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>\n        '
        prompt_dedent: str = dedent(prompt)
        api_args = {'model': model_name, 'max_tokens': 1024, 'messages': [{'role': 'user', 'content': prompt_dedent}]}
        if schema is not None:
            api_args['tools'] = schema

        # Log API request at DEBUG level
        logger.debug(
            "Anthropic API request",
            extra={
                'operation': 'anthropic_api_request',
                'model': model_name,
                'mode': 'json',
                'max_tokens': 1024,
                'has_tools': schema is not None
            }
        )

        start_time = datetime.now()
        response = client.messages.create(**api_args)
        duration = (datetime.now() - start_time).total_seconds()

        # Log API response at DEBUG level
        logger.debug(
            "Anthropic API response",
            extra={
                'operation': 'anthropic_api_response',
                'model': model_name,
                'duration': duration,
                'stop_reason': response.stop_reason,
                'usage': {
                    'input_tokens': response.usage.input_tokens if response.usage else None,
                    'output_tokens': response.usage.output_tokens if response.usage else None
                }
            }
        )
        response_content: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = next((block.input for block in response.content if hasattr(block, 'input')), None)
        if response_content is None:
            text_content = next((block.text for block in response.content if hasattr(block, 'text')), 'No text content available')
            from agent_actions.errors import VendorAPIError  # New modular pattern!
            raise VendorAPIError("No valid content with 'input' found in response", context={'model_name': model_name, 'vendor': 'anthropic', 'text_content': text_content[:200], 'api_operation': 'messages.create'})
        return response_content

    @staticmethod
    def call_non_json(api_key: Optional[str], agent_config: Dict[str, Any], prompt_config: Dict[str, Any], context_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Non-JSON mode is not implemented for Claude."""
        from agent_actions.errors import ConfigurationError  # New modular pattern!
        raise ConfigurationError('Non-JSON mode not implemented for Claude', context={'vendor': 'anthropic', 'supported_modes': ['json'], 'model_name': agent_config.get(MODEL_NAME_KEY)})