import cohere
import os
import json 

class CohereHandler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        api_key = os.getenv(agent_config['api_key'])
        model_name = agent_config['model_name']

        co = cohere.Client(api_key=api_key)
        prompt = f"""
            prompt_config: {prompt_config}
            Using this Input: {input_documentation}
            with the fields {', '.join([f"'{field}'" for field in schema.keys()])}

        """
        print(prompt)
        
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




