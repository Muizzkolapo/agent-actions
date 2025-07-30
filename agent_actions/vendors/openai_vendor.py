import json
from textwrap import dedent
from openai import OpenAI
from agent_actions.common.transformers.string_transformer import StringProcessor
from agent_actions.vendors.base_vendor import BaseVendorHandler
from agent_actions.constants import MODEL_NAME_KEY


class OpenAIHandler(BaseVendorHandler):
    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        client = OpenAI(api_key=api_key)

        model_name = agent_config[MODEL_NAME_KEY]

        context_data_str = StringProcessor.process_as_string(context_data)

        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            RULES: ALWAYS READ INPUT AS STRING
        """

        messages = [
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
        response_content = response_message.content
        response_data = json.loads(response_content)
        response_list = response_data if isinstance(response_data, list) else [response_data]
        return response_list

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        client = OpenAI(api_key=api_key)

        model_name = agent_config[MODEL_NAME_KEY]

        context_data_str = StringProcessor.process_as_string(context_data)

        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>
        """

        messages = [
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
        output_field = agent_config.get("output_field", "raw_response")
        response_content = {output_field: response_message.content}

        return [response_content]


