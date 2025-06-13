import cohere
import os
import json
from textwrap import dedent
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.vendors.base_vendor import BaseVendorHandler


class CohereHandler(BaseVendorHandler):
    @staticmethod
    def call_json(agent_config, prompt_config, context_data, schema):
        api_key = BaseVendorHandler.get_api_key(agent_config)
        model_name = agent_config['model_name']
        context_data_str = StringProcessor.process_as_string(context_data)
        co = cohere.Client(api_key=api_key)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {context_data_str} :<|end_of_text|>
            <|begin_of_output_schema|> : GENERATE JSON with the fields {', '.join([f"'{field}'" for field in schema.keys()])} : <|end_of_output_schema|>
            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            """ 
        prompt_dedent = dedent(prompt)       
        response = co.chat(
            model=model_name,
            message=prompt_dedent,
            response_format={
                "type": "json_object"
            }
        )

        intermediate_json = response.text 
        final_data = json.loads(intermediate_json)        
        return final_data  
   


    @staticmethod
    def call_non_json(agent_config, prompt_config, context_data):
        api_key = BaseVendorHandler.get_api_key(agent_config)
        co = cohere.ClientV2(api_key=api_key)
        model_name = agent_config['model_name']

        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>
        """
        messages=[
                {
                    "role": "user",
                    "content": dedent(prompt)
                }
            ]     
        response = co.chat(
            model=model_name,
            messages=messages
        )

        response_message = response.message.content[0].text

        return [response_message]




