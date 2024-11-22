import os
import json
import google.generativeai as genai
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.transformers.data_transformer import DataTransformer
import logging
from textwrap import dedent

logging.basicConfig(level=logging.ERROR)


class GeminiHandler:
    @staticmethod
    def call_json(agent_config, prompt_config, input_documentation, schema):
        api_key = agent_config['api_key']
        genai.configure(api_key=os.environ[api_key])
        model_name = agent_config['model_name']

        llm = genai.GenerativeModel(
            model_name,
            system_instruction="Return only JSON",
            generation_config={"response_mime_type": "application/json"}
        )
        
        input_documentation_str = StringProcessor.process_as_string(input_documentation)
        
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(input_documentation_str)} :<|end_of_text|>
            <|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            RULES: ALWAYS READ INPUT AS STRING
        """
        prompt_dedent = dedent(prompt)
        response_temp = llm.generate_content(prompt_dedent)
        response = json.loads(response_temp.text)
        response_list = DataTransformer.ensure_list(response)
        return response_list

    @staticmethod
    def call_non_json(agent_config, prompt_config, input_documentation):
        api_key = agent_config['api_key']
        genai.configure(api_key=os.environ[api_key])
        model_name = agent_config['model_name']

        llm = genai.GenerativeModel(
            model_name,
            system_instruction="Return only JSON",
            generation_config={"response_mime_type": "application/json"}
        )
        input_documentation_str = StringProcessor.process_as_string(input_documentation)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(input_documentation_str)} :<|end_of_text|>
        """
        prompt_dedent = dedent(prompt)
        response_temp = llm.generate_content(prompt_dedent)
        response_list = response_temp.text
        return [response_list]

    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        """
        Determine which function to call (JSON or non-JSON) based on the 'json_mode' parameter in agent_config.
        """
        json_mode = agent_config.get('json_mode', True)


        if json_mode:
            return GeminiHandler.call_json(agent_config, prompt_config, input_documentation, schema)
        else:
            return GeminiHandler.call_non_json(agent_config, prompt_config, input_documentation)

