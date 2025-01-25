import json
from openai import OpenAI
import os
from agent_actions.transformers.string_transformer import StringProcessor


class DeepSeekHandler:
    @staticmethod
    def call_json(agent_config, prompt_config, context_data, schema):
        api_key_config = agent_config['api_key']
        api_key = os.environ[api_key_config]
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

        model_name = agent_config['model_name']

        context_data_str = StringProcessor.process_as_string(context_data)

        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            RULES: RETURN JSON

             "json_schema": {str(schema)} 
        """

        messages = [
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": context_data_str
            }
        ]

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={
                "type": "json_object"
            }
        )

        response_message = response.choices[0].message
        response_content = response_message.content
        response_data = json.loads(response_content)
        return response_data

    @staticmethod
    def call_non_json(agent_config, prompt_config, context_data):
        pass

    @staticmethod
    def invoke(agent_config, prompt_config, context_data, schema):
        """
        Determine which function to call (JSON or non-JSON) based on the 'json_mode' parameter in agent_config.
        """
        json_mode = agent_config.get('json_mode', True)

        if json_mode:
            return DeepSeekHandler.call_json(agent_config, prompt_config, context_data, schema)
        else:
            return DeepSeekHandler.call_non_json(agent_config, prompt_config, context_data) 