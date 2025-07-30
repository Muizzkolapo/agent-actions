import json
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union

import google.generativeai as genai
from agent_actions.common.transformers.string_transformer import StringProcessor
from agent_actions.vendors.base_vendor import BaseVendorHandler
from agent_actions.constants import MODEL_NAME_KEY



class GeminiHandler(BaseVendorHandler):
    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        genai.configure(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]

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
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        genai.configure(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]

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


