import os
import json
import google.generativeai as genai
from agent_actions.core.utils import process_as_string




def ensure_list(obj):
    if not isinstance(obj, list):
        return [obj]
    return obj

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
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {input_documentation_str} :<|end_of_text|>
            <|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            RULES: ALWAYS READ INPUT AS STRING
        """
        response_temp = llm.generate_content(prompt)
        response = json.loads(response_temp.text)
        response_list = ensure_list(response)
        return response_list
