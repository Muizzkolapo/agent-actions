import json
from textwrap import dedent
from openai import OpenAI
import os
from agent_actions.transformers.string_transformer import StringProcessor


class OpenAIHandler:
    @staticmethod
    def call_json(agent_config, prompt_config, context_data, schema):
        api_key_config = agent_config['api_key']
        api_key = os.environ[api_key_config]
        client = OpenAI(api_key=api_key)

        model_name = agent_config['model_name']

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
        print(response_data)

        response_list = response_data if isinstance(response_data, list) else [response_data]
        return response_list

    @staticmethod
    def call_non_json(agent_config, prompt_config, context_data):
        api_key_config = agent_config['api_key']
        api_key = os.environ[api_key_config]
        client = OpenAI(api_key=api_key)

        model_name = agent_config['model_name']

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
        response_content = {"raw_response": response_message.content}

        return [response_content]

    @staticmethod
    def invoke(agent_config, prompt_config, context_data, schema):
        """
        Determine which function to call (JSON or non-JSON) based on the 'json_mode' parameter in agent_config.
        """
        json_mode = agent_config.get('json_mode', True)


        if json_mode:
            return OpenAIHandler.call_json(agent_config, prompt_config, context_data, schema)
        else:
            return OpenAIHandler.call_non_json(agent_config, prompt_config, context_data)

