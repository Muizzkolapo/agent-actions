"""
Module containing utility functions for data aggregation and transformation.
"""
import copy
import os
import traceback
import yaml
import re
import uuid

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
                    placeholder = f"get[{key}]"
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
                placeholder = f"get[{key}]"
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
    Replace the placeholder 'get_from_src[guid]' with the specified GUID
    in various data structures, including lists of strings, nested lists, and dictionaries.

    Parameters:
    data (list): The data to process, which can include lists of strings, nested lists, or dictionaries.
    guid (str): The GUID to replace the placeholder with.

    Returns:
    list: The updated data with the placeholder replaced.
    """

    def replace_in_string(text):
        return text.replace('get_from_src[guid]', guid)

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