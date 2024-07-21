"""Module for target loader."""

import json
import os
import traceback
try:
    from agent_actions.agent_utils.agent_builder import agent_builder
    from agent_actions.agent_utils.processor.clean_target import clean_agent_output
    from agent_actions.agent_utils.transformers.aggregators import try_cleaning_functions,update_schema_objects
except ImportError:
    # Handle import error gracefully
    agent_builder = None
    try_cleaning_functions = None

import copy
def replace_placeholders(prompt, content_dict):
    def convert_to_string(value):
        if isinstance(value, list):
            return ", ".join([str(v) if isinstance(v, dict) else str(v) for v in value])
        return str(value)

    # Check if content_dict is a dictionary and has keys
    if not isinstance(content_dict, dict) or not content_dict:
        return prompt

    new_prompt = []
    for sublist in prompt:
        new_sublist = []
        for string in sublist:
            for key, value in content_dict.items():
                placeholder = f"get[{key}]"
                value = convert_to_string(value)
                string = string.replace(placeholder, value)
            new_sublist.append(string)
        new_prompt.append(new_sublist)
    
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
    save_output(new_data, file_path, base_directory, output_directory)

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
    select_list = {agent_config['agent_type']: agent_config['select_list']}
    keys_list = list(select_list.keys())


    for contents in data:
        formated_prompt=replace_placeholders(agent_config['prompt'],contents)
        generated_data = agent_builder.create_dynamic_agent(agent_config, agent_name, contents,formated_prompt)
        if should_update_schema(agent_config, keys_list, select_list):
            keys_to_update = select_list[agent_config['agent_type']]
            merged_questions = update_schema_objects(agent_config["schema_name"],
                                                     agent_name,
                                                     [contents],
                                                     flatten_nested_list(generated_data)[0],
                                                     keys_to_update)
            
            new_data.append(merged_questions[0])
        else:
            new_data.append(flatten_nested_list(generated_data)[0])

    return new_data

def should_update_schema(agent_config, keys_list, select_list):
    """
    Determines whether the schema should be updated based on the agent configuration.

    :param agent_config: Configuration dictionary for the agent
    :param keys_list: List of keys in the select list
    :param select_list: Dictionary containing the select list
    :return: Boolean indicating whether the schema should be updated
    """
    return agent_config['agent_type'] == keys_list[0] and select_list[agent_config['agent_type']]

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








def flatten_data(data, parent_key='', sep='_'):
    """
    Flattens a nested dictionary or list into a flat dictionary.

    :param data: The dictionary or list to flatten.
    :param parent_key: The base key string for nested items (used in recursion).
    :param sep: The separator between parent and child keys.
    :return: A flattened dictionary.
    """
    items = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key
            items.extend(flatten_data(value, new_key, sep=sep).items())
    elif isinstance(data, list):
        for i, value in enumerate(data):
            new_key = f"{parent_key}{sep}{i}" if parent_key else str(i)
            items.extend(flatten_data(value, new_key, sep=sep).items())
    else:
        items.append((parent_key, data))

    return dict(items)

def flatten_nested_list(data):
    """
    Identifies the key containing a list of objects in the given data and flattens the list.

    :param data: Dictionary containing a list of objects under an unknown key.
    :return: List of flattened dictionaries.
    """
    flattened_data = []

    # Identify the key containing the list of objects
    list_key = None
    for key, value in data.items():
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            list_key = key
            break

    if list_key is None:
        print("No key containing a list of objects was found in the input data.")
        return flattened_data

    for item in data[list_key]:
        flattened_item = flatten_data(item)
        flattened_data.append(flattened_item)

    return flattened_data

def flatten_nested_list(data):
    """
    Identifies the key containing a list of objects in the given data and flattens the list.

    :param data: Dictionary containing a list of objects under an unknown key.
    :return: List of flattened dictionaries.
    """
    flattened_data = []

    # Identify the key containing the list of objects
    list_key = None
    for key, value in data.items():
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            list_key = key
            break

    if list_key is None:
        print("No key containing a list of objects was found in the input data.")
        return flattened_data

    for item in data[list_key]:
        flattened_item = flatten_data(item)
        flattened_data.append(flattened_item)

    return flattened_data