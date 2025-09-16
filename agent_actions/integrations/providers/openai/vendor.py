import json
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union

from openai import OpenAI
from openai.types.chat import ChatCompletionUserMessageParam, ChatCompletionSystemMessageParam
from agent_actions.agents.transformers.string_transformer import StringProcessor
from agent_actions.integrations.providers.vendor_base import BaseVendorHandler
from agent_actions.core.constants import MODEL_NAME_KEY


class OpenAIHandler(BaseVendorHandler):
    @staticmethod
    def call_json(api_key: Optional[str], agent_config: Dict[str, Any], 
                  prompt_config: Dict[str, Any], context_data: Dict[str, Any], 
                  schema: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        client = OpenAI(api_key=api_key)

        model_name: str = agent_config[MODEL_NAME_KEY]

        context_data_str: str = StringProcessor.process_as_string(context_data)

        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            RULES: ALWAYS READ INPUT AS STRING
        """

        messages: List[ChatCompletionSystemMessageParam] = [
            {
                "role": "system",
                "content": dedent(prompt)
            }
        ]

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": schema
            }
        )

        response_message = response.choices[0].message
        response_content: Optional[str] = response_message.content
        if response_content is None:
            raise ValueError("Empty response content from OpenAI API")
        response_data: Union[Dict[str, Any], List[Dict[str, Any]]] = json.loads(response_content)
        response_list: List[Dict[str, Any]] = response_data if isinstance(response_data, list) else [response_data]
        return response_list

    @staticmethod
    def call_non_json(api_key: Optional[str], agent_config: Dict[str, Any], 
                      prompt_config: Dict[str, Any], context_data: Dict[str, Any]) -> List[Dict[str, str]]:
        client = OpenAI(api_key=api_key)

        model_name: str = agent_config[MODEL_NAME_KEY]

        context_data_str: str = StringProcessor.process_as_string(context_data)

        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>
        """

        messages: List[ChatCompletionUserMessageParam] = [
            {
                "role": "user",
                "content": dedent(prompt)
            }
        ]

        response = client.chat.completions.create(
            model=model_name,
            messages=messages
        )

        response_message = response.choices[0].message
        output_field: str = agent_config.get("output_field", "raw_response")
        content: Optional[str] = response_message.content
        if content is None:
            raise ValueError("Empty response content from OpenAI API")
        response_content: Dict[str, str] = {output_field: content}

        return [response_content]


