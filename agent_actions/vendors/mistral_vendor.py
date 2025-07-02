import json
from mistralai import Mistral
from agent_actions.transformers.string_transformer import StringProcessor
from textwrap import dedent
from agent_actions.vendors.base_vendor import BaseVendorHandler
from agent_actions.config_keys import MODEL_NAME_KEY

class MistralHandler(BaseVendorHandler):
    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]

        client = Mistral(api_key=api_key)

        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {context_data_str} :<|end_of_text|>
            <|begin_of_output_schema|> : {schema} : <|end_of_output_schema|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            """
        prompt_dedent = dedent(prompt) 
        messages = [
            {
                "role": "user",
                "content": prompt_dedent,
            }
        ]
        chat_response = client.chat.complete(
            model=model_name,
            response_format={"type": "json_object"},
            messages=messages,
        )

        data = json.loads(chat_response.choices[0].message.content)
        return data

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]

        client = Mistral(api_key=api_key)

        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {context_data_str} :<|end_of_text|>
            """
        prompt_dedent = dedent(prompt) 
        messages = [
            {
                "role": "user",
                "content": prompt_dedent,
            }
        ]
        chat_response = client.chat.complete(
            model=model_name,
            messages=messages,
        )
        response_output = chat_response.choices[0].message.content
        return [response_output]


