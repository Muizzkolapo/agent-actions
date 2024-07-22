# pylint: disable=no-name-in-module
"""Module for creating dynamic agents."""

import os
from langchain.chains import create_structured_output_runnable
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import os
import google.generativeai as genai
import json

try:
    from agent_actions.agent_utils.transformers.aggregators import load_schema
except ImportError:
    # Handle import error gracefully
    load_schema = None

def list_to_tuples(input_list):
    """Convert a list of lists to a list of tuples."""
    return [tuple(item) for item in input_list]

def create_dynamic_agent(agent_config, agent_name, input_documentation,formatted_prompt = None):
    """
    Create a dynamic agent based on the provided configuration.

    :param agent_config: Configuration for the prompt.
    :param model_name: Name of the language model.
    :param api_key: API key for the language model.
    :param schema_name: Name of the schema.
    :param input_documentation: Input documentation for the agent.
    :return: Result of the agent's invocation.
    """
    if formatted_prompt is not None:
        prompt_config = list_to_tuples(formatted_prompt)
    else:
        prompt_config = list_to_tuples(agent_config['prompt'])
    model_name = agent_config['model_name']
    api_key = os.getenv(agent_config['api_key'])
    schema_name = agent_config['schema_name']
    schema = load_schema(schema_name)
    llm = genai.GenerativeModel(model_name,
                                  # Set the `response_mime_type` to output JSON
                                  generation_config={"response_mime_type": "application/json"}) 
    prompt = f"""
        prompt_config: {prompt_config}
       Using this input Input: {input_documentation}
        schema: {schema}
        
        Return a list[schema]
    """
    

    response = llm.generate_content(prompt)

    return json.loads(response.text)
