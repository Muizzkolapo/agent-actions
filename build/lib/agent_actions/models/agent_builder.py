import json 
from agent_actions.vendors.openai_vendor import OpenAIHandler
from agent_actions.vendors.gemini_vendor import GeminiHandler
from agent_actions.vendors.cohere_vendor import CohereHandler
from agent_actions.vendors.mistral_vendor import MistralHandler
from agent_actions.core.utils import load_schema
from agent_actions.vendors.groq_vendor import GroqLlama3Handler



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
    if formatted_prompt is not None:
        prompt_config = formatted_prompt
    else:
        prompt_config = agent_config['prompt']
    model_vendor = agent_config['model_vendor']
    schema_name = agent_config['schema_name']
    schema = load_schema(schema_name)

    if model_vendor.lower() == 'openai':
        prompt_config = list_to_tuples(prompt_config)
        response = OpenAIHandler.invoke(agent_config, prompt_config, input_documentation, schema)
    elif model_vendor.lower() == 'gemini':
        response = GeminiHandler.invoke(agent_config, prompt_config, input_documentation, schema)
    elif model_vendor.lower() == 'cohere':
        response_cohere = CohereHandler.invoke(agent_config, prompt_config, input_documentation, schema)
        response = [response_cohere]
    elif model_vendor.lower() == 'mistral':
        response_cohere = MistralHandler.invoke(agent_config, prompt_config, input_documentation, schema)
        response = [response_cohere]
    elif model_vendor.lower() == 'groq_llama3':  # New logic for Groq Llama 3
        response_groq_llama = GroqLlama3Handler.invoke(agent_config, formatted_prompt, input_documentation, schema)
        response = [response_groq_llama]
        print(response)
    else:
        raise ValueError(f"Unsupported model vendor: {model_vendor}")
    
    return response
