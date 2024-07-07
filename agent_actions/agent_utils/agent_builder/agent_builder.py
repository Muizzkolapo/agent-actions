# pylint: disable=no-name-in-module
"""Module for creating dynamic agents."""

import os
from langchain.chains import create_structured_output_runnable
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

try:
    from agent_actions.agent_utils.transformers.aggregators import load_schema
except ImportError:
    # Handle import error gracefully
    load_schema = None

def list_to_tuples(input_list):
    """Convert a list of lists to a list of tuples."""
    return [tuple(item) for item in input_list]

def create_dynamic_agent(agent_config, agent_name, input_documentation):
    """
    Create a dynamic agent based on the provided configuration.

    :param agent_config: Configuration for the prompt.
    :param model_name: Name of the language model.
    :param api_key: API key for the language model.
    :param schema_name: Name of the schema.
    :param input_documentation: Input documentation for the agent.
    :return: Result of the agent's invocation.
    """
    prompt_config = list_to_tuples(agent_config['prompt'])
    model_name = agent_config['model_name']
    api_key = os.getenv(agent_config['api_key'])
    schema_name = agent_config['schema_name']
    llm = ChatOpenAI(model=model_name, temperature=0, api_key=api_key)
    prompt = ChatPromptTemplate.from_messages(prompt_config)
    schema = load_schema(schema_name)
    agent = create_structured_output_runnable(schema, llm, prompt)
    return agent.invoke({"input": input_documentation, "chat_history": []})
