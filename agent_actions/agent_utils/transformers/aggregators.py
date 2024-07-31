"""
Module containing utility functions for data aggregation and transformation.
"""
import copy
import os
import traceback
import yaml
import re


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


def update_schema_objects(schema, agent_name, data_old, data_new, keys_to_update):
    """
    Creates new objects by combining specific fields from new data with other fields from old data.

    This function takes objects from the old data, updates certain fields with values from the
    corresponding objects in the new data, and retains all other fields as they are.

    :param schema: JSON schema describing the structure and keys of the objects.
    :param agent_name: Name of the agent.
    :param data_old: List containing original objects.
    :param data_new: List containing new objects with updates.
    :param keys_to_update: List of keys for which values should be updated from the new objects.
    :return: List of new combined objects.
    """
    schema = load_schema(schema)

    if schema is None:
        print(f"Failed to load schema for agent '{agent_name}' and schema '{schema}'.")
        return None
    try:
        old_objects = data_old
        new_objects = data_new

        # Initialize an empty list to store the new combined objects
        combined_objects = []

        # Iterate through each pair of old and new objects assuming both lists are of the same length
        for old_obj, new_obj in zip(old_objects, new_objects):
            # Create a new combined object by copying the old object
            combined_object = copy.deepcopy(old_obj)

            # Update specified keys from the new object if they are defined in the schema
            for key in keys_to_update:
                if key in new_obj:
                    print(f"Updating key '{key}' from new object")
                    combined_object[key] = new_obj[key]

            combined_objects.append(combined_object)

        # Return the new list of combined objects
        return combined_objects
    except KeyError as e:
        print(f"KeyError: {e}. Please check that the schema and data structures are correct.")
    except Exception as e:
        print(f"An unexpected error occurred in update_schema_objects: {e}")
        traceback.print_exc()
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