"""
Module containing utility classes and functions for data aggregation, transformation, file operations, and string processing.
"""

import copy
import importlib
import os
import re
import sys
import textwrap
import traceback
import uuid
from collections import deque

import yaml


# File and Directory Operations

class FileHandler:
    """
    A class for handling file and directory operations.
    """

    @staticmethod
    def find_file_in_directory(directory, target_filename):
        """
        Recursively searches for a file in a directory.

        Parameters:
            directory (str): The base directory to start the search from.
            target_filename (str): The name of the file to find.

        Returns:
            str or None: The full path to the file or None if not found.
        """
        for root, _, files in os.walk(directory):
            if target_filename in files:
                return os.path.join(root, target_filename)
        return None

    @staticmethod
    def find_specific_folder(current_dir, parent_folder_name, folder_name):
        """
        Search for a specific folder within a directory specified by the parent folder name.

        Parameters:
            current_dir (str): The base directory to start searching from.
            parent_folder_name (str): The folder under which the specific folder is expected.
            folder_name (str): The name of the specific folder to search for.

        Returns:
            str or None: The full path to the folder if found, otherwise None.
        """
        for root, dirs, _ in os.walk(current_dir):
            if parent_folder_name in dirs:
                target_folder_path = os.path.join(root, parent_folder_name, folder_name)
                if os.path.isdir(target_folder_path):
                    return target_folder_path
        return None

    @staticmethod
    def find_agent_folder(working_directory, folder_name, base_dir):
        """
        Searches for a specific folder within the base directory.

        Parameters:
            working_directory (str): The base directory to start searching from.
            folder_name (str): The name of the folder to search for.
            base_dir (str): The base directory name.

        Returns:
            str or None: The full path to the folder if found, otherwise None.
        """
        base_path = os.path.join(working_directory, base_dir)
        for root, dirs, _ in os.walk(base_path):
            if folder_name in dirs:
                return os.path.join(root, folder_name)
        return None

    @staticmethod
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
        agent_config_dir = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_config')
        io_dir = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')

        if agent_config_dir is None:
            raise FileNotFoundError(f"Agent configuration directory not found for agent '{agent_name}'.")
        if io_dir is None:
            raise FileNotFoundError(f"IO directory not found for agent '{agent_name}'.")

        # Construct the few_shot_samples_path
        few_shot_samples_path = os.path.join(io_dir, 'few_shot_samples')
        if not os.path.exists(few_shot_samples_path):
            few_shot_samples_path = None

        return agent_config_dir, io_dir, few_shot_samples_path


# Schema and Prompt Loading

class SchemaLoader:
    """
    A class for loading schemas.
    """

    @staticmethod
    def load_schema(schema_name):
        """
        Retrieve and generate a JSON schema based on the schema name provided.

        Parameters:
            schema_name (str): The name of the schema to load.

        Returns:
            dict: The loaded schema as a dictionary.
        """
        try:
            current_dir = os.getcwd()
            schema_dir = os.path.join(current_dir, "schema")

            if not os.path.exists(schema_dir):
                raise FileNotFoundError("Schema directory not found.")

            schema_file_path = FileHandler.find_file_in_directory(schema_dir, f"{schema_name}.yml")

            if not schema_file_path:
                raise FileNotFoundError(f"Schema file not found: {schema_name}.yml")

            with open(schema_file_path, 'r', encoding='utf-8') as file:
                documents = yaml.safe_load(file)

            return documents

        except Exception as e:
            print(f"An error occurred in load_schema: {e}")
            traceback.print_exc()
            return None


class PromptLoader:
    """
    A class for loading prompts.
    """

    @staticmethod
    def extract_prompt(content, prompt_name):
        """
        Extracts a prompt from the content using the prompt_name.

        Parameters:
            content (str): The content containing the prompt.
            prompt_name (str): The name of the prompt to extract.

        Returns:
            str: The extracted prompt or "Prompt not found."
        """
        # Regular expression to match the prompt block
        pattern = re.compile(rf"\{{prompt {prompt_name}\}}(.*?)\{{end_prompt\}}", re.DOTALL)

        # Search for the prompt using the pattern
        match = pattern.search(content)

        if match:
            return match.group(1).strip()
        else:
            return "Prompt not found."

    @staticmethod
    def load_prompt(prompt_name):
        """
        Retrieve and generate a prompt based on the prompt name provided.

        Parameters:
            prompt_name (str): The name of the prompt to load, in the format 'filename.prompt_key'.

        Returns:
            str: The loaded prompt as a string.
        """
        try:
            current_dir = os.getcwd()
            prompt_dir = os.path.join(current_dir, "prompt_store")

            if not os.path.exists(prompt_dir):
                raise FileNotFoundError("Prompt directory not found.")

            # Extract the prompt file name and the prompt key
            prompt_file_name, prompt_key = prompt_name.split('.', 1)

            # Search for the file in the prompt directory
            prompt_file_path = FileHandler.find_file_in_directory(prompt_dir, f"{prompt_file_name}.md")

            if not prompt_file_path:
                raise FileNotFoundError(f"Prompt file not found: {prompt_file_name}.md")

            # Read the content of the prompt file
            with open(prompt_file_path, 'r', encoding='utf-8') as file:
                content = file.read()

            prompt_data = PromptLoader.extract_prompt(content, prompt_key)

            return prompt_data

        except Exception as e:
            print(f"An error occurred in load_prompt: {e}")
            traceback.print_exc()
            return None


# String Processing Functions

class StringProcessor:
    """
    A class for processing strings, including placeholder replacement and function call processing.
    """

    @staticmethod
    def process_as_string(input_text):
        """
        Ensures the input text is treated as a plain string, even if it contains dictionary-like patterns.

        Parameters:
            input_text (str): The input text that may contain dictionary-like patterns.

        Returns:
            str: The processed string treated as plain text.

        Raises:
            ValueError: If the input is not a string.
        """
        if not isinstance(input_text, str):
            raise ValueError("Input must be a string")
        pattern = re.compile(r'({.*?})')
        escaped_text = pattern.sub(lambda x: x.group(0).replace("{", "{{").replace("}", "}}"), input_text)
        return escaped_text

    @staticmethod
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
            placeholder_keys = [key.strip() for key in placeholder.split(',')]
            replacements = [f"{key}: {convert_to_string(content_dict[key])}" for key in placeholder_keys if key in content_dict]
            replacement_text = ', '.join(replacements)
            prompt = prompt.replace(f'return_collection[{placeholder}]', replacement_text)

        return prompt

    @staticmethod
    def replace_guid_placeholder(data, guid):
        """
        Replace the placeholder 'return_collection{{source_context}}' with the specified GUID in a string.

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

    @staticmethod
    def process_text_with_function_calls(text, tools_path=None, input_documentation_str=None):
        """
        Replace multiple dispatch_task() calls in text with the result of their corresponding function.
        Always passes `input_documentation_str` to the function.

        Parameters:
            text (str or list): The text containing dispatch_task() calls.
            tools_path (str): The path to the tools directory.
            input_documentation_str (str): Documentation string to pass to the functions.

        Returns:
            str or list: The text with dispatch_task() calls replaced by function outputs.
        """
        def process_single_text(single_text):
            function_call_pattern = r"dispatch_task\('(\w+)'\)"
            function_calls = re.findall(function_call_pattern, single_text)

            if not function_calls:
                return single_text

            for function_name in function_calls:
                try:
                    transformed_text = StringProcessor.call_user_function(function_name, tools_path, input_documentation_str)
                    if transformed_text is None:
                        transformed_text = "Error: No valid return from function."
                    single_text = single_text.replace(f"dispatch_task('{function_name}')", transformed_text, 1)
                except Exception as e:
                    print(f"Error calling function {function_name}: {e}")

            return single_text

        if isinstance(text, list):
            return [process_single_text(item) for item in text]
        else:
            return process_single_text(text)

    @staticmethod
    def call_user_function(function_name, tools_path=None, input_documentation_str=None):
        """
        Dynamically loads and executes a user-defined function from the tools folder.
        Always passes `input_documentation_str` as input.

        Parameters:
            function_name (str): Name of the function to call.
            tools_path (str): Path to the tools directory.
            input_documentation_str (str): Documentation string to pass to the function.

        Returns:
            Any: The result returned by the user function.

        Raises:
            Exception: If the function cannot be called or an error occurs.
        """
        try:
            if tools_path and tools_path not in sys.path:
                sys.path.insert(0, os.path.abspath(tools_path))
            module = importlib.import_module(function_name)
            function = getattr(module, function_name)
            result = function(input_documentation_str) if input_documentation_str else function()
            return result
        except Exception as exception:
            print(f"Error in call_user_function for {function_name}:")
            print(f"Exception type: {type(exception).__name__}")
            print(f"Exception message: {str(exception)}")
            print("Traceback:")
            traceback.print_exc()
            raise


# Data Manipulation Functions

class DataTransformer:
    """
    A class for data manipulation and transformation.
    """

    @staticmethod
    def update_schema_objects(data_old, data_new, keys_to_update):
        """
        Updates specified keys in old data with values from new data.

        Parameters:
            data_old (dict): Dictionary containing original data.
            data_new (dict): Dictionary containing new data with updates.
            keys_to_update (list): List of keys for which values should be updated from the new data.

        Returns:
            dict: Dictionary with updated values.

        Raises:
            KeyError: If a key is missing.
            Exception: For other exceptions.
        """
        try:
            # Create a new updated data by copying the old data
            updated_data = copy.deepcopy(data_old)

            # Update specified keys from the new data
            for key in keys_to_update:
                if key in data_new:
                    print(f"Updating key '{key}' from new data")
                    updated_data[key] = data_new[key]
            return updated_data

        except KeyError as e:
            print(f"KeyError: {e}. Please check the data structures.")
        except Exception as e:
            print(f"An unexpected error occurred in update_schema_objects: {e}")
            return None

    @staticmethod
    def extract_objects(input_data):
        """
        Extracts the list of summaries from the input dictionary.

        Parameters:
            input_data (dict or list): Dictionary containing a list of summaries under any key.

        Returns:
            list: List of summaries.
        """
        try:
            if isinstance(input_data, list):
                for field_name, field_value in input_data[0].items():
                    if isinstance(field_value, list):
                        return field_value
            else:
                for field_name, field_value in input_data.items():
                    if isinstance(field_value, list):
                        return field_value
        except Exception as e:
            print(f"An error occurred while extracting summaries: {e}")
        return []

    @staticmethod
    def flatten_to_list_of_dicts(nested_lists):
        """
        Flattens a nested list of lists containing dictionaries into a single list of dictionaries.

        Parameters:
            nested_lists (list): A nested list where each inner list contains dictionaries.

        Returns:
            list: A flat list containing all dictionaries from the nested structure.
        """
        flattened_list = []

        for sublist in nested_lists:
            flattened_list.extend(sublist)

        return flattened_list

    @staticmethod
    def transform_structure(data):
        """
        Transforms a list of dictionaries with nested contents into a flat list of dictionaries.

        Parameters:
            data (list): List of dictionaries to transform.

        Returns:
            list: Transformed list of dictionaries.
        """
        transformed_data = []
        for data_item in data:
            for guid, contents in data_item.items():
                for content in contents:
                    transformed_data.append({
                        "guid": guid,
                        "content": content
                    })
        return transformed_data

    @staticmethod
    def ensure_list(obj):
        """
        Ensures that the input object is a list.

        Parameters:
            obj (Any): The object to ensure as a list.

        Returns:
            list: The object wrapped in a list if it wasn't already a list.
        """
        if not isinstance(obj, list):
            return [obj]
        return obj


# Utility Functions

class Utils:
    """
    A class containing miscellaneous utility functions.
    """

    @staticmethod
    def generate_id():
        """
        Generate a unique identifier.

        Returns:
            str: A UUID4 unique identifier as a string.
        """
        return str(uuid.uuid4())

    @staticmethod
    def topological_sort(dependencies):
        """
        Perform a topological sort on the dependencies graph.

        Parameters:
            dependencies (dict): A dictionary representing the dependency graph where each key is a node and the value is a list of nodes it depends on.

        Returns:
            list: A list of nodes in topologically sorted order.

        Raises:
            ValueError: If there is a cycle in the dependencies.
        """
        in_degree = {node: 0 for node in dependencies}
        for node in dependencies:
            for dependent_node in dependencies[node]:
                in_degree[dependent_node] += 1

        queue = deque([node for node in in_degree if in_degree[node] == 0])
        sorted_nodes = []

        while queue:
            current_node = queue.popleft()
            sorted_nodes.append(current_node)
            for neighbor in dependencies[current_node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_nodes) != len(dependencies):
            raise ValueError("There is a cycle in the dependencies")

        return sorted_nodes[::-1]
