import os
import json
from groq import Groq  # Assuming this is the official Groq API Python package
from agent_actions.core.utils import process_as_string,ensure_list



class GroqLlama3Handler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        api_key = agent_config['api_key']
        groq = Groq(api_key=os.environ[api_key])
        model_name = agent_config['model_name']

        input_documentation_str = process_as_string(input_documentation)
        
        prompt = f"""
            {prompt_config}.\n
            WRITE OUTPUTS IN JSON SCHEMA: {json.dumps(schema)}.\n
            INPUT DATA: {input_documentation_str}
        """

        try:
            llm = groq.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": prompt,
                    }
                ],
                model=model_name,
                response_format={"type": "json_object"},
            )
            response_temp =  llm.choices[0].message.content
            response = json.loads(response_temp)
            response_list = ensure_list(response)
            return response_list

        except Exception as e:
            raise Exception(f"Failed to create chat completion with Groq Llama 3: {str(e)}")
