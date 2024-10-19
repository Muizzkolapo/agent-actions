import json
from agent_actions.vendors.openai_vendor import OpenAIHandler
from agent_actions.vendors.gemini_vendor import GeminiHandler
from agent_actions.vendors.cohere_vendor import CohereHandler
from agent_actions.vendors.mistral_vendor import MistralHandler
from agent_actions.vendors.groq_llama import GroqLlama3Handler
from agent_actions.vendors.tools_vendor import ToolHandler
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.handlers.agent_handlers import SchemaLoader, PromptLoader





def create_dynamic_agent(agent_config, udf, input_documentation_str, formatted_prompt=None, tools_path=None):
    """
    Create a dynamic agent based on the provided configuration, with support for transforming the prompt
    using user-defined Python functions specified in the configuration.

    :param agent_config: Configuration for the prompt.
    :param udf: User-defined functions.
    :param input_documentation_str: Input documentation for the agent.
    :param formatted_prompt: Preformatted prompt if available.
    :param tools_path: Path to the user's tools directory where custom functions are stored.
    :return: Result of the agent's invocation.
    """
    # Handle prompt loading first
    if formatted_prompt is not None:
        prompt_config = formatted_prompt
    else:
        prompt_config = agent_config.get('prompt', '')
        if isinstance(prompt_config, str) and prompt_config.startswith('$'):
            prompt_config = PromptLoader.load_prompt(prompt_config[1:])  

    if tools_path is None:
        tools_path = agent_config.get('tools', {}).get('path')

    input_documentation = json.dumps(input_documentation_str) 

    transformed_prompt_config = StringProcessor.process_text_with_function_calls(prompt_config, tools_path, input_documentation)
    
    prompt_config = transformed_prompt_config

    if agent_config.get('prompt_debug', False):
        print("\n" + "="*40)
        print("DEBUG: Prompt going into the agent:")
        print("="*40)
        print(prompt_config)
        print(formatted_prompt)
        print("="*40 + "\n")

    model_vendor = agent_config['model_vendor']
    
    schema_name = agent_config.get('schema_name') if model_vendor.lower() != 'tool' else None
    schema = SchemaLoader.load_schema(schema_name) if schema_name else None
    
    if model_vendor.lower() == 'openai':
        response = OpenAIHandler.invoke(agent_config, prompt_config, input_documentation, schema)
    elif model_vendor.lower() == 'gemini':
        response = GeminiHandler.invoke(agent_config, prompt_config, input_documentation, schema)
    elif model_vendor.lower() == 'cohere':
        response_cohere = CohereHandler.invoke(agent_config, prompt_config, input_documentation, schema)
        response = [response_cohere]
    elif model_vendor.lower() == 'mistral':
        response_cohere = MistralHandler.invoke(agent_config, prompt_config, input_documentation, schema)
        response = [response_cohere]
    elif model_vendor.lower() == 'groq_llama3': 
        response_groq_llama = GroqLlama3Handler.invoke(agent_config, formatted_prompt, input_documentation, schema)
        response = [response_groq_llama]
    elif model_vendor.lower() == 'tool': 
        response_ToolHandler = ToolHandler.invoke(agent_config, input_documentation)
        response = [response_ToolHandler]
    else:
        raise ValueError(f"Unsupported model vendor: {model_vendor}")
    
    return response
