import anthropic
client = anthropic.Anthropic()
from textwrap import dedent
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.vendors.base_vendor import BaseVendorHandler
from agent_actions.constants import MODEL_NAME_KEY


class ClaudeHandler(BaseVendorHandler):
    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]
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

        response_content = next(
            (block.input for block in response.content if hasattr(block, 'input')),
            None
        )
        if response_content is None:
            # Handle cases where no suitable content block is found
            raise ValueError("No valid content with 'input' found in response")
        return response_content

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        """Non-JSON mode is not implemented for Claude."""
        raise NotImplementedError("Non-JSON mode not implemented for Claude")
   






