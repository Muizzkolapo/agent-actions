import json
from textwrap import dedent
from openai import OpenAI
import logging
import os 

logging.basicConfig(level=logging.ERROR)

class OpenAIHandler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        api_key_config = agent_config['api_key']
        api_key =os.environ[api_key_config]  
        client = OpenAI(api_key=api_key)

        model_name = agent_config['model_name']

        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            RULES: ALWAYS READ INPUT AS STRING
            RULES: return list of schema object
        """

        messages = [
            {
                "role": "system",
                "content": dedent(prompt)
            },
            {
                "role": "user",
                "content": input_documentation
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