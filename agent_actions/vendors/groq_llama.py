import os
import json
from groq import Groq  # Assuming this is the official Groq API Python package
from agent_actions.transformers.string_transformer import StringProcessor
from textwrap import dedent
from agent_actions.transformers.data_transformer import DataTransformer



class GroqLlama3Handler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        api_key = agent_config['api_key']
        groq = Groq(api_key=os.environ[api_key])
        model_name = agent_config['model_name']

        input_documentation_str = StringProcessor.process_as_string(input_documentation)
        
        prompt = f"""
            <|begin_of_user_instruction|>:{prompt_config} :<|end_of_user_instruction|>\n
            <|begin_of_text|>:: {input_documentation_str} :<|end_of_text|>\n
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
            raise Exception(f"Failed to create chat completion with Groq Llama 3: {str(e)}")
