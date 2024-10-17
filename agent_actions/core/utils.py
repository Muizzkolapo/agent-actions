"""
Module containing utility functions for data aggregation and transformation.
"""
import copy
import os
import traceback
import yaml
import re
import importlib
import sys
import uuid
from collections import deque, OrderedDict
import textwrap

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
    """
    Replace placeholders in the prompt string with values from content_dict.

    Parameters:
    prompt (str): The prompt string containing placeholders.
    content_dict (dict): A dictionary containing the values to replace placeholders.

    Returns:
    str: The prompt with placeholders replaced by actual values.
    """
    def convert_to_string(value):
        if isinstance(value, list):
            return ", ".join([str(v) if isinstance(v, dict) else str(v) for v in value])
        return str(value)

    # Check if content_dict is a dictionary and has keys
    if not isinstance(content_dict, dict) or not content_dict:
        return prompt

    # Find placeholders in the format return_collection[key1,key2]
    placeholders = re.findall(r'return_collection\[(.*?)\]', prompt)
    for placeholder in placeholders:
        keys = [key.strip() for key in placeholder.split(',')]
        values = [f"{key}: {convert_to_string(content_dict[key])}" for key in keys if key in content_dict]
        replacement = ', '.join(values)
        prompt = prompt.replace(f'return_collection[{placeholder}]', replacement)

    return prompt


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
    in a string.

    Parameters:
    data (str): The string to process.
    guid (str): The GUID to replace the placeholder with.

    Returns:
    str: The updated string with the placeholder replaced.
    """
    if not isinstance(data, str):
        return data

    replaced_data = data.replace('return_collection{{source_context}}', guid)
    cleaned_content = textwrap.dedent(replaced_data).strip()
    return cleaned_content

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
            - few_shot_samples_path (str or None): Path to the agent's sample output directory, or None if it doesn't exist.
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
        few_shot_samples_path = None

    return agent_config_dir, io_dir, few_shot_samples_path





def process_text_with_function_calls(text, tools_path=None, input_documentation_str=None):
    """
    Replace multiple dispatch_task() calls in text with the result of their corresponding function.
    Always passes `input_documentation_str` to the function.

    Parameters:
    text (str): The input text containing dispatch_task() calls.
    tools_path (str): The path to the tools module.
    input_documentation_str (str): The input documentation string to pass to each function.

    Returns:
    str: The processed text with dispatch_task() calls replaced by their results.
    """
    # Regex to match dispatch_task('function_name')
    function_call_pattern = r"dispatch_task\('(\w+)'\)"
    matches = re.findall(function_call_pattern, text)

    if not matches:
        return text  # Return original text if no dispatch_task calls are found

    # Process each function call individually to avoid conflicts
    for function_name in matches:
        try:
            # Call the user-defined function and pass input_documentation_str
            transformed_text = call_user_function(function_name, tools_path, input_documentation_str)
            # Ensure transformed_text is a string
            if transformed_text is None:
                transformed_text = "Error: No valid return from function."
            # Replace only the specific dispatch_task instance with the transformed text
            text = text.replace(f"dispatch_task('{function_name}')", transformed_text, 1)
        except Exception as e:
            print(f"Error calling function {function_name}: {e}")

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