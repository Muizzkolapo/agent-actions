import json
import re
from agent_actions.vendors.openai_vendor import OpenAIHandler
from agent_actions.vendors.gemini_vendor import GeminiHandler
from agent_actions.vendors.cohere_vendor import CohereHandler
from agent_actions.vendors.mistral_vendor import MistralHandler
from agent_actions.core.utils import load_schema
from agent_actions.vendors.groq_llama import GroqLlama3Handler
import importlib
import sys
import os


def list_to_tuples(input_list):
    """Convert a list of lists to a list of tuples."""
    return [tuple(item) for item in input_list]
def process_text_with_function_calls(text, tools_path=None, input_documentation_str=None):
    """
    Replace call_function() in text with the result of the function call.
    Always passes `input_documentation_str` to the function.
    """
    print(f"Original text: {text}")

    # Regex to match call_function('function_name')
    function_call_pattern = r"call_function\('(\w+)'\)"
    matches = re.findall(function_call_pattern, text)

    if matches:
        print(f"Found function calls: {matches}")

    for function_name in matches:
        # Always pass the input_documentation_str to the function
        print(f"Calling function: {function_name} with input_documentation_str")
        try:
            transformed_text = call_user_function(function_name, tools_path, input_documentation_str)
            print(f"Function {function_name} returned: {transformed_text}")
            # Replace the call_function() placeholder with the transformed text
            text = text.replace(f"call_function('{function_name}')", transformed_text)
        except Exception as e:
            print(f"Error calling function {function_name}: {e}")

    print(f"Transformed text: {text}")
    return text


def call_user_function(function_name, tools_path=None, input_documentation_str=None):
    """
    Dynamically loads and executes a user-defined function from the tools folder.
    Always passes `input_documentation_str` as input.
    """
    try:
        if tools_path and tools_path not in sys.path:
            sys.path.insert(0, os.path.abspath(tools_path))  # Ensure tools_path is correctly added to sys.path

        # Import the module (ensure it's in tools_path)
        module = importlib.import_module(function_name)
        function = getattr(module, function_name)
        # Pass input_documentation_str as the argument
        result = function(input_documentation_str) if input_documentation_str else function()
        return result
    except Exception as e:
        print(f"Error loading function {function_name}: {e}")
        raise


def create_dynamic_agent(agent_config, agent_name, input_documentation_str, formatted_prompt=None, tools_path=None):
    """
    Create a dynamic agent based on the provided configuration, with support for transforming the prompt
    using user-defined Python functions specified in the configuration.

    :param agent_config: Configuration for the prompt.
    :param agent_name: Name of the agent.
    :param input_documentation_str: Input documentation for the agent.
    :param formatted_prompt: Preformatted prompt if available.
    :param tools_path: Path to the user's tools directory where custom functions are stored.
    :return: Result of the agent's invocation.
    """
    print(formatted_prompt)
    input_documentation = json.dumps(input_documentation_str) 
    if formatted_prompt is not None:
        prompt_config = formatted_prompt
    else:
        prompt_config = agent_config['prompt']

    # Dynamically transform the prompt using Python functions, always passing input_documentation_str
    transformed_prompt_config = []
    for p in prompt_config:
        transformed_text = process_text_with_function_calls(p, tools_path, input_documentation_str)
        transformed_prompt_config.append(transformed_text)

    prompt_config = transformed_prompt_config

    model_vendor = agent_config['model_vendor']
    schema_name = agent_config['schema_name']
    schema = load_schema(schema_name)

    if model_vendor.lower() == 'openai':
        prompt_config = list_to_tuples(prompt_config)
        response = OpenAIHandler.invoke(agent_config, prompt_config, input_documentation, schema)
    elif model_vendor.lower() == 'gemini':
        print(prompt_config)
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
    else:
        raise ValueError(f"Unsupported model vendor: {model_vendor}")
    
    return response