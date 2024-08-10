import os
import json
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
from agent_actions.core.utils import process_as_string

class MistralHandler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        api_key = os.getenv(agent_config['api_key'])
        api_key = os.environ["MISTRAL_API_KEY"]
        model_name = agent_config['model_name']

        client = MistralClient(api_key=api_key)

        input_documentation_str = process_as_string(input_documentation)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {input_documentation_str} :<|end_of_text|>
            <|begin_of_output_schema|> : {schema} : <|end_of_output_schema|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            """
        messages = [
            ChatMessage(role="user", content=prompt)
        ]

        chat_response = client.chat(
            model=model_name,
            response_format={"type": "json_object"},
            messages=messages,
        )

        data = json.loads(chat_response.choices[0].message.content)
        return data
