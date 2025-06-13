import os
import json
from groq import Groq  # Assuming this is the official Groq API Python package
from agent_actions.transformers.string_transformer import StringProcessor
from textwrap import dedent
from agent_actions.cli.exceptions import VendorAPIError
from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.vendors.base_vendor import BaseVendorHandler



class GroqLlama3Handler(BaseVendorHandler):
    @staticmethod
    def call_json(agent_config, prompt_config, context_data, schema):
        api_key = BaseVendorHandler.get_api_key(agent_config)
        groq = Groq(api_key=api_key)
        model_name = agent_config['model_name']

        context_data_str = StringProcessor.process_as_string(context_data)
        
        prompt = f"""
            <|begin_of_user_instruction|>:{prompt_config} :<|end_of_user_instruction|>\n
            <|begin_of_text|>:: {context_data_str} :<|end_of_text|>\n
            <|begin_of_output_schema|> :WRITE OUTPUTS IN JSON SCHEMA: {json.dumps(schema)}. : <|end_of_output_schema|>
        """
        prompt_dedent = dedent(prompt)   

        try:
            llm = groq.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": prompt_dedent,
                    }
                ],
                model=model_name,
                response_format={"type": "json_object"},
            )
            response_temp =  llm.choices[0].message.content
            response = json.loads(response_temp)
            response_list = DataTransformer.ensure_list(response)
            return response_list
        except Exception as e:
            # Catch specific Groq API errors if available, e.g., groq.APIError
            raise VendorAPIError(f"Failed to create chat completion with Groq Llama 3: {str(e)}") from e

    @staticmethod
    def call_non_json(agent_config, prompt_config, context_data):
        api_key = BaseVendorHandler.get_api_key(agent_config)
        groq = Groq(api_key=api_key)
        model_name = agent_config['model_name']
        context_data_str = StringProcessor.process_as_string(context_data)


        prompt = f"""
                Instructions: {prompt_config}
                Input Text: {str(context_data_str)}
                
                Please provide a direct response without any JSON formatting.
                Begin your response here:
            """

        prompt_dedent = dedent(prompt).strip()
        completion_kwargs = {
            "messages": [
                {
                    "role": "system",
                    "content": prompt_dedent,
                }
            ],
            "model": model_name,
            "temperature": 0.7,   
            "max_tokens": 1000,   
        }
        response = groq.chat.completions.create(**completion_kwargs)
        try:
            response_content = response.choices[0].message.content
            return [response_content]
        except (AttributeError, IndexError, TypeError) as e:
            raise VendorAPIError(f"Error parsing non-JSON response from Groq Llama 3: {str(e)}. Response: {response}") from e
        except Exception as e: # Catch other Groq API errors
            raise VendorAPIError(f"Failed to get non-JSON chat completion from Groq Llama 3: {str(e)}") from e

