from agent_actions.agent_utils.agent_builder.vendors.openai_vendor import OpenAIHandler
from agent_actions.agent_utils.agent_builder.vendors.gemini_vendor import GeminiHandler
from agent_actions.agent_utils.agent_builder.vendors.mistral_vendor import MistralHandler
from agent_actions.agent_utils.agent_builder.vendors.cohere_vendor import CohereHandler
import json 

try:
    from agent_actions.agent_utils.transformers.aggregators import load_schema,extract_objects,process_as_string
except ImportError:
    # Handle import error gracefully
    load_schema = None
    extract_objects = None
    process_as_string = None
def list_to_tuples(input_list):
    """Convert a list of lists to a list of tuples."""
    return [tuple(item) for item in input_list]

def create_dynamic_agent(agent_config, agent_name, input_documentation_str, formatted_prompt=None):
    """
    Create a dynamic agent based on the provided configuration.

    :param agent_config: Configuration for the prompt.
    :param agent_name: Name of the agent.
    :param input_documentation: Input documentation for the agent.
    :param formatted_prompt: Preformatted prompt if available.
    :return: Result of the agent's invocation.
    """
    input_documentation = json.dumps(input_documentation_str) 

    
    model_vendor = agent_config['model_vendor']
    schema_name = agent_config['schema_name']
    schema = load_schema(schema_name)

    if model_vendor.lower() == 'openai':
        if formatted_prompt is not None:
            prompt_config = list_to_tuples(formatted_prompt)
        else:
            prompt_config = list_to_tuples(agent_config['prompt'])
        response = OpenAIHandler.invoke(agent_config, prompt_config, input_documentation, schema)
    elif model_vendor.lower() == 'gemini':
        if formatted_prompt is not None:
            prompt_config = formatted_prompt
        else:
            prompt_config = agent_config['prompt']
        response = GeminiHandler.invoke(agent_config, prompt_config, input_documentation, schema)
    elif model_vendor.lower() == 'mistral':
        if formatted_prompt is not None:
            prompt_config = formatted_prompt
        else:
            prompt_config = agent_config['prompt']
        response_mistral = MistralHandler.invoke(agent_config, prompt_config, input_documentation, schema)
        response = [response_mistral]
    elif model_vendor.lower() == 'cohere':
        if formatted_prompt is not None:
            prompt_config = formatted_prompt
        else:
            prompt_config = agent_config['prompt']
        response_cohere = CohereHandler.invoke(agent_config, prompt_config, input_documentation, schema)
        response = [response_cohere]
    else:
        raise ValueError(f"Unsupported model vendor: {model_vendor}")
    
    return response
