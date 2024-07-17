"""Module for target loader."""

import json
import os

try:
    from agent_actions.agent_utils.agent_builder import agent_builder
    from agent_actions.agent_utils.processor.clean_target import clean_agent_output
    from agent_actions.agent_utils.transformers.aggregators import try_cleaning_functions
except ImportError:
    # Handle import error gracefully
    agent_builder = None
    try_cleaning_functions = None

import copy

def replace_placeholders(prompt, content_dict):
    new_prompt = copy.deepcopy(prompt)
    for i, sublist in enumerate(new_prompt):
        for j, string in enumerate(sublist):
            for key, value in content_dict.items():
                placeholder = f"get[{key}]"
                if placeholder in string:
                    new_prompt[i][j] = string.replace(placeholder, value)
    return new_prompt

def generate_target(agent_config, agent_name, file_path, base_directory, output_directory):
    """
    Generates target data based on the agent configuration and input file,
    and writes the output to the specified directory.

    :param agent_config: Configuration dictionary for the agent
    :param agent_name: Name of the agent
    :param file_path: Path to the input JSON file
    :param base_directory: Base directory for calculating relative paths
    :param output_directory: Directory where the output file will be saved
    """
    data = load_json(file_path)
    new_data = process_data(data, agent_config, agent_name)
    final_data = try_cleaning_functions(new_data)
    save_output(final_data, file_path, base_directory, output_directory)

def load_json(file_path):
    """
    Loads JSON data from a given file path.

    :param file_path: Path to the input JSON file
    :return: Parsed JSON data as a list of dictionaries
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def process_data(data, agent_config, agent_name):
    """
    Processes the input data based on the agent configuration and generates new data.

    :param data: List of dictionaries containing the input data
    :param agent_config: Configuration dictionary for the agent
    :param agent_name: Name of the agent
    :return: List of dictionaries containing the processed data
    """
    new_data = []
    for contents in data:
        formatted_prompt = replace_placeholders(agent_config['prompt'], contents)
        generated_data = agent_builder.create_dynamic_agent(agent_config, agent_name, contents,formatted_prompt)
        new_data.append(generated_data)
    return new_data


def save_output(new_data, file_path, base_directory, output_directory):
    """
    Saves the processed data to the specified output directory.

    :param new_data: List of dictionaries containing the processed data
    :param file_path: Path to the input JSON file
    :param base_directory: Base directory for calculating relative paths
    :param output_directory: Directory where the output file will be saved
    """
    relative_path = os.path.relpath(file_path, base_directory)
    output_file_path = os.path.join(output_directory, relative_path.replace('.json', '.json'))
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
    with open(output_file_path, 'w', encoding='utf-8') as file:
        json.dump(new_data, file, indent=4)
