import cohere
import os
import json 
from agent_actions.agent_utils.transformers.aggregators  import process_as_string


class CohereHandler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        api_key = os.getenv(agent_config['api_key'])
        model_name = agent_config['model_name']
        input_documentation_str = process_as_string(input_documentation)
        co = cohere.Client(api_key=api_key)
        prompt = f"""
            <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
            <|begin_of_text|>: {input_documentation_str} :<|end_of_text|>
            <|begin_of_output_schema|> : {', '.join([f"'{field}'" for field in schema.keys()])} : <|end_of_output_schema|>

            RULES: YOU CANNOT RETURN THE CONTENT OF OUTPUT SCHEMA IN YOUR OUTPUT
            """        
        response = co.chat(
            model=model_name,
            message=prompt,
            response_format={
                "type": "json_object"
            }
        )

        intermediate_json = response.text 
        final_data = json.loads(intermediate_json)        
        return final_data  




