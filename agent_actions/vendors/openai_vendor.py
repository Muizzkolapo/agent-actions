import json
from textwrap import dedent
from openai import OpenAI
import logging

logging.basicConfig(level=logging.ERROR)

class OpenAIHandler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        # Set up the API key and client
        api_key = agent_config['api_key']
        client = OpenAI(api_key=api_key)

        # Retrieve the model name from the agent configuration
        model_name = agent_config['model_name']

        # Use the prompt configuration as the system prompt
        math_tutor_prompt = prompt_config

        # The question is provided as the input documentation
        question = input_documentation

        # Prepare the messages for the chat completion
        messages = [
            {
                "role": "system",
                "content": dedent(math_tutor_prompt)
            },
            {
                "role": "user",
                "content": question
            }
        ]

        # Make the API call to OpenAI's ChatCompletion via client.chat.completions.create
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": schema
            }
        )

        # Extract the response message
        response_message = response.choices[0].message

        # Parse the JSON content from the response
        response_content = response_message.content  # Use dot notation instead of subscripting
        response_data = json.loads(response_content)

        # Ensure the response is a list
        response_list = response_data if isinstance(response_data, list) else [response_data]
        print(response_list)

        return response_list