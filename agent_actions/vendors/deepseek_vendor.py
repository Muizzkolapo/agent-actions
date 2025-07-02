import json
from openai import OpenAI
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.vendors.base_vendor import BaseVendorHandler
from agent_actions.config_keys import MODEL_NAME_KEY


class DeepSeekHandler(BaseVendorHandler):
    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

        model_name = agent_config[MODEL_NAME_KEY]

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
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        pass
