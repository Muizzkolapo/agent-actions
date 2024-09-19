"""
Module containing utility functions for data aggregation and transformation.
"""
import copy
import os
import traceback
import yaml
import re
import uuid
from collections import deque, OrderedDict

def load_schema(schema_name):
    """
    Retrieve and generate a JSON schema based on the schema name provided.
    """
    try:
        current_dir = os.getcwd()
        schema_dir = os.path.join(current_dir, "schema")

        if schema_dir is None:
            raise FileNotFoundError(f"Schema directory not found.")

        schema_file_path = find_file_in_directory(schema_dir, f"{schema_name}.yml")

        if not schema_file_path:
            raise FileNotFoundError(f"Schema file not found: {schema_name}.yml")

        with open(schema_file_path, 'r', encoding='utf-8') as file:
            documents = yaml.safe_load(file)

        return documents

    except FileNotFoundError as fnf_error:
        print(f"Error: {fnf_error}")
    except yaml.YAMLError as yaml_error:
        print(f"YAML parsing error: {yaml_error}")
    except ValueError as ve:
        print(f"Value Error: {ve}")
    except Exception as e:
        print(f"An unexpected error occurred in load_schema: {e}")
        traceback.print_exc()

def find_file_in_directory(directory, target_filename):
    """
    Recursively searches for a file in a directory.

    :param directory: The base directory to start the search from.
    :param target_filename: The name of the file to find.
    :return: The full path to the file or None if not found.
    """
    for root, _, files in os.walk(directory):
        if target_filename in files:
            return os.path.join(root, target_filename)
    return None


def update_schema_objects(data_old, data_new, keys_to_update):
    """
    Updates specified keys in old data with values from new data.

    :param data_old: Dictionary containing original data.
    :param data_new: Dictionary containing new data with updates.
    :param keys_to_update: List of keys for which values should be updated from the new data.
    :return: Dictionary with updated values.
    """
    try:
        # Create a new combined object by copying the old object
        combined_object = copy.deepcopy(data_old)

        # Update specified keys from the new object
        for key in keys_to_update:
            if key in data_new:
                print(f"Updating key '{key}' from new data")
                combined_object[key] = data_new[key]
        return combined_object

    except KeyError as e:
        print(f"KeyError: {e}. Please check the data structures.")
    except Exception as e:
        print(f"An unexpected error occurred in update_objects: {e}")
        return None

def extract_objects(input_data):
    """
    Extracts the list of summaries from the input dictionary.

    :param input_data: Dictionary containing a list of summaries under any key.
    :return: List of summaries.
    """
    try:
        if isinstance(input_data, list):
            for key, value in input_data[0].items():
                if isinstance(value, list):
                    return value
        else:
            for key, value in input_data.items():
                if isinstance(value, list):
                    return value
    except Exception as e:
        print(f"An error occurred while extracting summaries: {e}")
    return []




def process_as_string(input_text):
    """
    This function ensures the input text is treated as a plain string,
    even if it contains dictionary-like patterns.

    Args:
    input_text (str): The input text that may contain dictionary-like patterns.

    Returns:
    str: The processed string treated as plain text.
    """
    # Ensure the input is a string
    if not isinstance(input_text, str):
        raise ValueError("Input must be a string")

    # Pattern to identify dictionary-like structures
    pattern = re.compile(r'({.*?})')

    # Escape curly braces to avoid interpretation as dictionary-like structures
    escaped_text = pattern.sub(lambda x: x.group(0).replace("{", "{{").replace("}", "}}"), input_text)
    
    return escaped_text

def flatten_to_list_of_dicts(nested_lists):
    """
    Flattens a nested list of lists containing dictionaries into a single list of dictionaries.
    
    Args:
        nested_lists (list): A nested list where each inner list contains dictionaries.
        
    Returns:
        list: A flat list containing all dictionaries from the nested structure.
    """
    # Initialize an empty list to store the dictionaries
    flattened_list = []
    
    # Iterate over each sublist in the nested lists
    for sublist in nested_lists:
        # Extend the flattened list with dictionaries from the current sublist
        flattened_list.extend(sublist)
    
    return flattened_list


def replace_placeholders(prompt, content_dict):
    def convert_to_string(value):
        if isinstance(value, list):
            return ", ".join([str(v) if isinstance(v, dict) else str(v) for v in value])
        return str(value)

    # Check if content_dict is a dictionary and has keys
    if not isinstance(content_dict, dict) or not content_dict:
        return prompt

    new_prompt = []
    for element in prompt:
        if isinstance(element, list):
            # Process as a sublist
            new_sublist = []
            for string in element:
                for key, value in content_dict.items():
                    placeholder = f"return_collection[{key}]"
                    value = convert_to_string(value)
                    string = string.replace(placeholder, value) 
                new_sublist.append(string)
            new_prompt.append(new_sublist)
        elif isinstance(element, dict):
            # Process dictionary entries
            new_dict = {}
            for key, value in element.items():
                for k, v in content_dict.items():
                    placeholder = f"get[{k}]"
                    v = convert_to_string(v)
                    new_key = key.replace(placeholder, v)
                    new_value = value.replace(placeholder, v) if isinstance(value, str) else value
                    new_dict[new_key] = new_value
            new_prompt.append(new_dict)
        else:
            # Process as a single string
            for key, value in content_dict.items():
                placeholder = f"return_collection[{key}]"
                value = convert_to_string(value)
                element = element.replace(placeholder, value)
            new_prompt.append(element)
    
    return new_prompt


def transform_structure(data):
    transformed_data = []
    # Iterate over each dictionary in the list
    for item in data:
        # Extract the GUID and the content list
        for guid, contents in item.items():
            # Iterate over each content dictionary in the contents list
            for content in contents:
                transformed_data.append({
                    "guid": guid,
                    "content": content
                })
    return transformed_data



def replace_guid_placeholder(data, guid):
    """
    Replace the placeholder 'return_collection{{source_context}}' with the specified GUID
    in various data structures, including lists of strings, nested lists, and dictionaries.

    Parameters:
    data (list): The data to process, which can include lists of strings, nested lists, or dictionaries.
    guid (str): The GUID to replace the placeholder with.

    Returns:
    list: The updated data with the placeholder replaced.
    """

    def replace_in_string(text):
        return text.replace('return_collection{{source_context}}', guid)

    def process_item(item):
        if isinstance(item, str):
            return replace_in_string(item)
        elif isinstance(item, list):
            return [process_item(sub_item) for sub_item in item]
        elif isinstance(item, dict):
            return {key: process_item(value) for key, value in item.items() if isinstance(value, str)}
        else:
            return item

    # Process each element in the input data
    return [process_item(item) for item in data]

def generate_id():
    """Generate a unique identifier."""
    return str(uuid.uuid4())

def ensure_list(obj):
    if not isinstance(obj, list):
        return [obj]
    return obj


def find_specific_folder(current_dir, filename, folder_name):
    """
    Search for a specific folder within a directory specified by the filename.

    Parameters:
    current_dir (str): The base directory to start searching from.
    filename (str): The folder under which the specific folder is expected.
    folder_name (str): The name of the specific folder to search for.

    Returns:
    str or None: The full path to the folder if found, otherwise None.
    """
    for root, dirs, files in os.walk(current_dir):
        if filename in dirs:
            target_folder_path = os.path.join(root, filename, folder_name)
            if os.path.isdir(target_folder_path):
                return target_folder_path
    return None








def topological_sort(dependencies):
    """
    Perform a topological sort on the dependencies graph.
    """
    in_degree = {u: 0 for u in dependencies}
    for u in dependencies:
        for v in dependencies[u]:
            in_degree[v] += 1

    queue = deque([u for u in in_degree if in_degree[u] == 0])
    ordered = []

    while queue:
        vertex = queue.popleft()
        ordered.append(vertex)
        for neighbor in dependencies[vertex]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(ordered) != len(dependencies):
        raise ValueError("There is a cycle in the dependencies")

    return ordered[::-1]


def find_agent_folder(working_directory, folder_name,base_dir):
    # Define the base path to search within
    base_path = os.path.join(working_directory, base_dir)    
    # Walk through the directory tree
    for root, dirs, files in os.walk(base_path):
        if folder_name in dirs:
            # Return the full path to the matching folder
            return os.path.join(root, folder_name)
    
    # If the folder is not found, return None
    return None








def get_agent_paths(agent_name):
    """
    Returns the agent configuration directory, IO directory, and sample output path for the given agent name.

    Parameters:
        agent_name (str): The name of the agent.

    Returns:
        tuple: A tuple containing:
            - agent_config_dir (str): Path to the agent's configuration directory.
            - io_dir (str): Path to the agent's IO directory.
            - few_shot_samples_path (str): Path to the agent's sample output directory.
    """
    current_dir = os.getcwd()
    agent_config_dir = find_specific_folder(current_dir, agent_name, 'agent_config')
    io_dir = find_specific_folder(current_dir, agent_name, 'agent_io')
    
    if agent_config_dir is None:
        raise FileNotFoundError(f"Agent configuration directory not found for agent '{agent_name}'.")
    if io_dir is None:
        raise FileNotFoundError(f"IO directory not found for agent '{agent_name}'.")

    # Construct the few_shot_samples_path
    few_shot_samples_path = os.path.join(io_dir, 'few_shot_samples')
    if not os.path.exists(few_shot_samples_path):
        raise FileNotFoundError(f"Sample output directory not found at '{few_shot_samples_path}'.")

    return agent_config_dir, io_dir, few_shot_samples_path