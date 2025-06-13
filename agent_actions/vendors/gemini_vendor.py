import os
import json
import google.generativeai as genai
from agent_actions.transformers.string_transformer import StringProcessor
from textwrap import dedent



class GeminiHandler:
    @staticmethod
    def call_json(agent_config, prompt_config, context_data, schema):
        api_key = agent_config['api_key']
        genai.configure(api_key=os.environ[api_key])
        model_name = agent_config['model_name']

        llm = genai.GenerativeModel(
            model_name,
            system_instruction="Return only JSON",
            generation_config={"response_mime_type": "application/json"}
        )
        
        context_data_str = StringProcessor.process_as_string(context_data)
        
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>
            <|begin_of_output_schema|> : list of this [{schema}] : <|end_of_output_schema|>

            RULES: DO NOT ADD ANY KEY NOT IN PROVIDED SCHEMA LIST
        """
        prompt_dedent = dedent(prompt)
        response_temp = llm.generate_content(prompt_dedent)
        response = json.loads(response_temp.text)
        return response

    @staticmethod
    def call_non_json(agent_config, prompt_config, context_data):
        api_key = agent_config['api_key']
        genai.configure(api_key=os.environ[api_key])
        model_name = agent_config['model_name']

        llm = genai.GenerativeModel(
            model_name,
            system_instruction="Return only JSON",
            generation_config={"response_mime_type": "application/json"}
        )
        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>
        """
        prompt_dedent = dedent(prompt)
        response_temp = llm.generate_content(prompt_dedent)
        response_list = response_temp.text
        return [response_list]

    @staticmethod
    def invoke(agent_config, prompt_config, context_data, schema):
        """
        Determine which function to call (JSON or non-JSON) based on the 'json_mode' parameter in agent_config.
        """
        json_mode = agent_config.get('json_mode', True)


        if json_mode:
            return GeminiHandler.call_json(agent_config, prompt_config, context_data, schema)
        else:
            return GeminiHandler.call_non_json(agent_config, prompt_config, context_data)

