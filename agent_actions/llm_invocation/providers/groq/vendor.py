import json
from groq import Groq
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from textwrap import dedent
from agent_actions.errors import VendorAPIError  # New modular pattern!
from agent_actions.preprocessing.transformation.data_transformer import DataTransformer
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.utilities.constants import MODEL_NAME_KEY

class GroqLlama3Handler(BaseVendorHandler):

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        groq = Groq(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f'\n            <|begin_of_user_instruction|>:{prompt_config} :<|end_of_user_instruction|>\n\n            <|begin_of_text|>:: {context_data_str} :<|end_of_text|>\n\n            <|begin_of_output_schema|> :WRITE OUTPUTS IN JSON SCHEMA: {json.dumps(schema)}. : <|end_of_output_schema|>\n        '
        prompt_dedent = dedent(prompt)
        try:
            llm = groq.chat.completions.create(messages=[{'role': 'system', 'content': prompt_dedent}], model=model_name, response_format={'type': 'json_object'})
            response_temp = llm.choices[0].message.content
            response = json.loads(response_temp)
            response_list = DataTransformer.ensure_list(response)
            return response_list
        except Exception as e:
            raise VendorAPIError('Failed to create chat completion with Groq Llama 3', context={'model_name': model_name, 'vendor': 'groq', 'api_operation': 'chat.completions.create'}, cause=e)

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        groq = Groq(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f'\n                Instructions: {prompt_config}\n                Input Text: {str(context_data_str)}\n                \n                Please provide a direct response without any JSON formatting.\n                Begin your response here:\n            '
        prompt_dedent = dedent(prompt).strip()
        completion_kwargs = {'messages': [{'role': 'system', 'content': prompt_dedent}], 'model': model_name, 'temperature': 0.7, 'max_tokens': 1000}
        response = groq.chat.completions.create(**completion_kwargs)
        try:
            response_content = response.choices[0].message.content
            return [response_content]
        except (AttributeError, IndexError, TypeError) as e:
            raise VendorAPIError('Error parsing non-JSON response from Groq Llama 3', context={'model_name': model_name, 'vendor': 'groq', 'response': str(response)[:200]}, cause=e)
        except Exception as e:
            raise VendorAPIError('Failed to get non-JSON chat completion from Groq Llama 3', context={'model_name': model_name, 'vendor': 'groq', 'api_operation': 'chat.completions.create'}, cause=e)