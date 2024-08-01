import os
import json
import google.generativeai as genai
from agent_actions.agent_utils.transformers.aggregators  import process_as_string

class GeminiHandler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        api_key = agent_config['api_key']
        genai.configure(api_key=os.environ[api_key])
        model_name = agent_config['model_name']

        llm = genai.GenerativeModel(
            model_name,
            system_instruction="Return only JSON",
            generation_config={"response_mime_type": "application/json"}
        )
        
        input_documentation_str = process_as_string(input_documentation)
        prompt = f"""
            prompt_config: {prompt_config}
            Using this input Input: {input_documentation_str}
            schema: {schema}
            Return a list[schema]
        """
        response_temp = llm.generate_content(prompt)
        response = json.loads(response_temp.text)
        return response
