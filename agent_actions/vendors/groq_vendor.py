import os
import json
from groq import Groq  # Assuming this is the official Groq API Python package
from agent_actions.core.utils import process_as_string

class GroqLlama3Handler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        api_key = agent_config['api_key']
        print(os.environ[api_key])
        groq = Groq(api_key=os.environ[api_key])
        model_name = agent_config['model_name']

        input_documentation_str = process_as_string(input_documentation)
        
        prompt = f"""
            You are helpful memory recorder.\n
            Write outputs in JSON in schema: {json.dumps(schema)}.\n
            {prompt_config}\n
            {input_documentation_str}
        """

        try:
            chat_completion = groq.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": prompt,
                    }
                ],
                model=model_name,
                response_format={"type": "json_object"},
            )
            return chat_completion.choices[0].message.content

        except Exception as e:
            raise Exception(f"Failed to create chat completion with Groq Llama 3: {str(e)}")
