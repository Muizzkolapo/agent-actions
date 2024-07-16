"""
Module containing utility functions for data aggregation and transformation.
"""
import copy
import os
import traceback
import yaml

try:
    from agent_actions.agent_utils.processor.process_target import find_agent_folder
except ImportError:
    # Handle import error gracefully
    find_agent_folder = None


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

def update_schema_objects(schema_name, agent_name, data_old, data_new, keys_to_update):
    """
    Updates specific fields in objects within a list based on a JSON schema and specified keys
    from new data.

    This function takes objects from the old data, updates certain fields with values from the
    corresponding objects in the new data, and retains all other fields as they are.

    :param schema_name: Name of the JSON schema describing the structure and keys of the objects.
    :param agent_name: Name of the agent.
    :param data_old: Dictionary containing a key with a list of original objects.
    :param data_new: Dictionary containing a key with a list of new objects with updates.
    :param keys_to_update: List of keys for which values should be updated from the new objects.
    :return: A dictionary containing the list of updated objects.
    """
    schema = load_schema(schema_name)

    if schema is None:
        print(f"Failed to load schema for agent '{agent_name}' and schema '{schema_name}'.")
        return None

    try:
        # Dynamically identify the key for the list of objects, as defined by the schema
        main_key = next(k for k, v in schema['properties'].items() if v.get('type') == 'array')

        old_objects = data_old[main_key]
        new_objects = data_new[main_key]

        # Initialize an empty list to store the updated objects
        updated_objects = []

        # Iterate through each pair of old and new object assuming both lists are of the same length
        for old_obj, new_obj in zip(old_objects, new_objects):
            # Use deep copy to avoid modifying the original dictionary
            updated_object = copy.deepcopy(old_obj)

            # Update specified keys from the new object if they are defined in the schema
            object_properties = schema['properties'][main_key]['items']['properties']
            for key in keys_to_update:
                if key in new_obj and key in object_properties:
                    updated_object[key] = new_obj[key]

            # Append the updated object to the list
            updated_objects.append(updated_object)

        # Return the new data structure with updated objects
        return {main_key: updated_objects}
    except KeyError as e:
        print(f"KeyError: {e}. Please check that the schema and data structures are correct.")
    except Exception as e:
        print(f"An unexpected error occurred in update_schema_objects: {e}")
        traceback.print_exc()
        return None


def extract_all_lists(data):
    """
    Extract all lists from a list of dictionaries.
    """
    all_lists = []
    for item in data:
        # Iterate over all key-value pairs in the item
        for value in item.values():
            # Check if the value is a list
            if isinstance(value, list):
                all_lists.extend(value)
    return all_lists


def flatten_nested_dictionaries(data):
    """
    Flattens a list of dictionaries containing nested dictionaries under any key into a single
    list of dictionaries.

    :param data: List of dictionaries where each dictionary may contain any key with a list of
                 nested dictionaries.
    :return: List of flattened dictionaries.
    """
    flattened = []
    for item in data:
        for value in item.values():
            if isinstance(value, list) and all(isinstance(elem, dict) for elem in value):
                flattened.extend(value)
    return flattened

def try_cleaning_functions(data):
    """
    Tries to clean the data using two different functions, and returns the cleaned data.
    If both functions return None, returns the raw data.

    :param data: The raw data to clean
    :return: Cleaned data or raw data if both cleaning functions return None
    """
    result = extract_all_lists(data)
    if result is not None:
        return result

    result = flatten_nested_dictionaries(data)
    if result is not None:
        return result

    return data