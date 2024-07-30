# pylint: disable=no-name-in-module
"""Module for creating dynamic agents."""

import os
import json
from langchain.chains import create_structured_output_runnable
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import google.generativeai as genai

try:
    from agent_actions.agent_utils.transformers.aggregators import load_schema,extract_summaries
except ImportError:
    # Handle import error gracefully
    load_schema = None
    extract_summaries = None

def list_to_tuples(input_list):
    """Convert a list of lists to a list of tuples."""
    return [tuple(item) for item in input_list]

def create_dynamic_agent(agent_config, agent_name, input_documentation, formatted_prompt=None):
    """
    Create a dynamic agent based on the provided configuration.

    :param agent_config: Configuration for the prompt.
    :param agent_name: Name of the agent.
    :param input_documentation: Input documentation for the agent.
    :param formatted_prompt: Preformatted prompt if available.
    :return: Result of the agent's invocation.
    """
    if formatted_prompt is not None:
        prompt_config = list_to_tuples(formatted_prompt)
    else:
        prompt_config = list_to_tuples(agent_config['prompt'])
    
    model_name = agent_config['model_name']
    model_vendor = agent_config['model_vendor']
    api_key = os.getenv(agent_config['api_key'])
    schema_name = agent_config['schema_name']
    schema = load_schema(schema_name)

    if model_vendor.lower() == 'openai':
        llm = ChatOpenAI(model=model_name, temperature=0, api_key=api_key)
        prompt = ChatPromptTemplate.from_messages(prompt_config)
        agent = create_structured_output_runnable(schema, llm, prompt)
        transformed_response = extract_summaries(agent.invoke({"input": input_documentation, "chat_history": []}))
        return transformed_response
    
    elif model_vendor.lower() == 'gemini':
        api_key = agent_config['api_key']
        genai.configure(api_key=os.environ[api_key])
        llm = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
        prompt = f"""
            prompt_config: {prompt_config}
            Using this input Input: {input_documentation}
            schema: {schema}
            Return a list[schema]
        """
        response = llm.generate_content(prompt)
        transformed_response = extract_summaries(json.loads(response.text))
        return transformed_response
    
    else:
        raise ValueError(f"Unsupported model name: {model_name}")