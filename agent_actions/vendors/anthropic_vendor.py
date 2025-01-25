import anthropic
client = anthropic.Anthropic()
import os
import json 
from textwrap import dedent
from agent_actions.transformers.string_transformer import StringProcessor


class ClaudeHandler:
    @staticmethod
    def call_json(agent_config, prompt_config, context_data, schema):
        api_key_config = agent_config['api_key']
        api_key = os.environ[api_key_config]
        model_name = agent_config['model_name']
        client = anthropic.Anthropic(api_key=api_key)
        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>
        """
        prompt_dedent = dedent(prompt)      
        response = client.messages.create(
            model=model_name,
            max_tokens=1024,
            tools= schema,
            messages=[{"role": "user", "content":prompt_dedent}]
        )

        response_content = response.content[1].input
        return response_content  
   



    @staticmethod
    def invoke(agent_config, prompt_config, context_data, schema):
        """
        Determine which function to call (JSON or non-JSON) based on the 'json_mode' parameter in agent_config.
        """
        json_mode = agent_config.get('json_mode', True)


        if json_mode:
            return ClaudeHandler.call_json(agent_config, prompt_config, context_data, schema)
        else:
            return ClaudeHandler.call_non_json(agent_config, prompt_config, context_data)



