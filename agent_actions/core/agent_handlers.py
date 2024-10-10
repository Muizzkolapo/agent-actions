import json 
import traceback
import importlib
import os 
from agent_actions.core.utils import find_specific_folder
import shutil
import random
import logging
import tiktoken
from typing import List

logger = logging.getLogger(__name__)



def clean_agent_directories(agent_name):
    """
    Deletes all files under the staging, source, and target folders for the specified agent.

    :param agent_name: Name of the agent
    """
    current_dir = os.getcwd()
    agent_folder = find_specific_folder(current_dir, agent_name, 'agent_io')

    if agent_folder is None:
        print(f"Agent folder not found for agent: {agent_name}")
        return

    staging_dir = os.path.join(agent_folder, 'staging')
    source_dir = os.path.join(agent_folder, 'source')
    target_dir = os.path.join(agent_folder, 'target')

    for directory in [staging_dir, source_dir, target_dir]:
        if os.path.exists(directory):
            shutil.rmtree(directory)
            print(f"Deleted directory: {directory}")
        else:
            print(f"Directory not found: {directory}")


def validate_agent_config(agent_config):
    """
    Validate the agent configuration to ensure all required fields are present and correctly formatted.
    """
    base_required_keys = {'agent_type', 'model_name'}
    tool_required_keys = {'description'}
    additional_required_keys = {'api_key', 'schema_name', 'prompt'}

    for idx, agent in enumerate(agent_config):
        # Determine the required keys based on the model_vendor
        if agent.get('model_vendor') == 'tool':
            required_keys = base_required_keys.union(tool_required_keys)
        else:
            required_keys = base_required_keys.union(additional_required_keys)
        
        missing_keys = required_keys - agent.keys()
        if missing_keys:
            return False, f"Agent {idx + 1} is missing required keys: {', '.join(missing_keys)}"

        # Ensure dependencies is a list if it exists, otherwise set it to an empty list
        if 'dependencies' in agent and not isinstance(agent['dependencies'], list):
            return False, f"Agent {idx + 1}: 'dependencies' should be a list."
        agent.setdefault('dependencies', [])

    return True, "Agent configuration is valid."

def num_tokens_from_string(string: str, encoding_name: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens

def split_text_content(text: str, chunk_size: int, overlap: int, encoding_name: str = "cl100k_base") -> List[str]:
    """Split text into chunks of a specified size with a specified overlap."""
    tokens = tiktoken.get_encoding(encoding_name).encode(text)
    chunks = []
    start_idx = 0
    while start_idx < len(tokens):
        end_idx = min(start_idx + chunk_size, len(tokens))
        chunk = tokens[start_idx:end_idx]
        decoded_chunk = tiktoken.get_encoding(encoding_name).decode(chunk)
        chunks.append(decoded_chunk)
        start_idx += chunk_size - overlap
    print(chunks)
    return chunks

def clean_agent_output(agent_name, agent_type, function_name):
    """
    Cleans the agent output by applying a specified function to each JSON file
    in the target directory of the agent.

    :param agent_name: Name of the agent
    :param agent_type: Type of the agent
    :param function_name: Name of the function to apply to the JSON data
    """
    project_root = os.getcwd()  # Get current working directory
    input_directory = os.path.join(project_root, 'agent_io', agent_name, 'target', agent_type)
    function_call = globals().get(function_name)
    if function_call and callable(function_call):
        for root, _, files in os.walk(input_directory):
            for file_name in files:
                if file_name.endswith('.json'):
                    file_path = os.path.join(root, file_name)
                    with open(file_path, 'r', encoding='utf-8') as file:
                        data = json.load(file)
                    flattened_data = function_call(data)
                    with open(file_path, 'w', encoding='utf-8') as file:
                        json.dump(flattened_data, file, indent=4)



def get_folder(agent_name):
    """
    Retrieves the folder name immediately following 'agent_config' for the given agent.

    :param agent_name: The name of the agent.
    :return: The folder name or None if not found.
    """
    agent_config_dir = os.path.join(os.getcwd(), 'agent_config')
    filename = f"{agent_name}.yml" if not agent_name.endswith(".yml") else agent_name
    full_path = find_config_file(agent_config_dir, filename)
    return get_folder_after_agent_config(full_path),full_path






def process_and_generate_for_agent(agent_config,
                                   agent_name,
                                   previous_agent_type,
                                   loader,
                                   function_name):
    """
    Processes and generates data for an agent by applying a specified function
    to each file in the input directory and saving the output in the target directory.

    :param agent_config: Configuration dictionary for the agent.
    :param agent_name: Name of the agent.
    :param previous_agent_type: Type of the previous agent, if applicable.
    :param loader: Name of the loader module.
    :param function_name: Name of the function to apply to the data.
    """
    try:
        current_dir = os.getcwd()
        agent_folder = find_specific_folder(current_dir,agent_name,'agent_io')
        
        if agent_folder is None:
            raise FileNotFoundError(f"Agent folder not found for agent: {agent_name}")

        input_directory = os.path.join(
            agent_folder,
            'target',
            previous_agent_type
        ) if previous_agent_type else os.path.join(
            agent_folder,
            'staging'
        )

        output_directory = os.path.join(
            agent_folder,
            'target',
            agent_config["agent_type"]
        )

        try:
            module = importlib.import_module(f"agent_actions.processors.{loader}")
            function_call = getattr(module, function_name)
        except (ImportError, AttributeError) as e:
            print(f"Failed to import {function_name} from module {loader}: {e}")
            traceback.print_exc()
            return

        if function_call and callable(function_call):
            files_processed = False
            for root, _, files in os.walk(input_directory):
                if files:
                    files_processed = True
                for file in files:
                    file_path = os.path.join(root, file)
                    print(f"Processing {file_path}")
                    try:
                        function_call(agent_config,
                                      agent_name,
                                      file_path,
                                      input_directory,
                                      output_directory)
                    except (IOError, OSError, json.JSONDecodeError) as e:
                        print(f"Failed to process {file}: {e}")
                    except ValueError as e:
                        print(f"Invalid data encountered while processing {file}: {e}")
                    except KeyError as e:
                        print(f"Missing key encountered while processing {file}: {e}")

            if not files_processed:
                print(f"No files found in the input directory: {input_directory}")
        else:
            print(f"Function {function_name} not found in module {loader}.")
            traceback.print_exc()
        return output_directory  # Return the output directory path
    except FileNotFoundError as fnf_error:
        print(f"File not found error: {fnf_error}")
    except Exception as e:
        print(f"An error occurred in process_and_generate_for_agent: {e}")
        traceback.print_exc()


import os
import logging

logger = logging.getLogger(__name__)

def find_config_file(base_dir, filename):
    logger.info(f"Searching for {filename} in {base_dir}")
    for root, _, files in os.walk(base_dir):
        if filename in files:
            full_path = os.path.join(root, filename)
            logger.info(f"Found config file: {full_path}")
            return full_path
    
    # If not found, search in parent directories
    parent_dir = os.path.dirname(base_dir)
    if parent_dir != base_dir:  # Ensure we're not at the root
        return find_config_file(parent_dir, filename)
    
    logger.warning(f"Config file {filename} not found in {base_dir} or its parent directories")
    return None



def should_update_schema(agent_config, keys_list, side_collection):
    """
    Determines whether the schema should be updated based on the agent configuration.

    :param agent_config: Configuration dictionary for the agent
    :param keys_list: List of keys in the select list
    :param side_collection: Dictionary containing the select list
    :return: Boolean indicating whether the schema should be updated
    """
    return agent_config['agent_type'] == keys_list[0] and side_collection[agent_config['agent_type']]

def get_content_by_guid(data, guid):
    """
    Retrieve the content associated with a specific GUID from a list of dictionaries.

    Parameters:
    data (list of dict): The list containing dictionaries with GUIDs as keys.
    guid (str): The GUID to search for.

    Returns:
    str: The content associated with the GUID, or a message if not found.
    """
    # Iterate through the list of dictionaries
    for item in data:
        # Check if the guid is a key in the dictionary
        if guid in item:
            return item[guid]
    # Return None or an appropriate message if not found
    return "GUID not found."


def get_folder_after_agent_config(path):
    """
    Extracts the folder name immediately following 'agent_config' in a given path.

    :param path: The file path to analyze.
    :return: The folder name following 'agent_config' or None if not found.
    """
    path_components = path.split(os.sep)

    if 'agent_config' in path_components:
        agent_config_index = path_components.index('agent_config')

        if agent_config_index + 1 == len(path_components) - 1 and os.path.isfile(path):
            return '(isfile)'

        if agent_config_index + 1 < len(path_components):
            return path_components[agent_config_index + 1]

    return None





def get_all_agent_paths(base_dir):
    """
    Get a list of all agent configuration file paths within the base directory.
    """
    agent_paths = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".yml"):
                agent_paths.append(os.path.join(root, file))
    return agent_paths


def check_agent_name_unique(agent_name, base_dir):
    """
    Check if the agent name is unique across the entire project.
    """
    all_agent_paths = get_all_agent_paths(base_dir)
    agent_names = [os.path.splitext(os.path.basename(path))[0] for path in all_agent_paths]
    return agent_names.count(agent_name) == 1


def check_agent_file_unique(full_path, base_dir):
    """
    Check if the agent configuration file path is unique across the entire project.
    """
    all_agent_paths = get_all_agent_paths(base_dir)
    return all_agent_paths.count(full_path) == 1


def find_agents_name(config):
    """
    Find the name of the agent from the configuration.
    """
    return next(iter(config))





def load_few_shot_samples(few_shot_samples_path, agent_type, sample_count=3):
    """
    Load random sample objects from the JSON files in the sample output directory for a specific agent type.

    Parameters:
        few_shot_samples_path (str): Base path to the sample output directory.
        agent_type (str): The type of the agent to load samples for.
        sample_count (int): Number of random sample objects to load.

    Returns:
        list: List of randomly selected sample objects.
    """

    agent_samples_path = os.path.join(few_shot_samples_path, agent_type)
    if not os.path.exists(agent_samples_path):
        return []

    sample_files = [f for f in os.listdir(agent_samples_path) if f.endswith('.json')]
    all_samples = []

    for sample_file in sample_files:
        with open(os.path.join(agent_samples_path, sample_file), 'r') as file:
            data = json.load(file)
            if isinstance(data, list):
                all_samples.extend(data)
            elif isinstance(data, dict):
                all_samples.append(data)

    if sample_count > 0 and all_samples:
        selected_samples = random.sample(all_samples, min(sample_count, len(all_samples)))
    else:
        selected_samples = []
    return selected_samples



def get_file_info(file_path):
    # Check if the file exists
    if not os.path.exists(file_path):
        return f"File '{file_path}' does not exist."

    # Extract the directory and file name from the file path
    dir_path, file_name = os.path.split(file_path)

    # Extract the path up to the 'summary_agent' directory
    agent_dir = os.path.dirname(dir_path)

    # Define the source path as '/source' at the same level as 'staging'
    source_path = os.path.join(agent_dir, 'source')

    # Join the file name with the source path
    source_file_path = os.path.join(source_path, file_name)

    # Check if the source path exists
    if os.path.exists(source_path):
        return source_file_path
    else:
        return None
