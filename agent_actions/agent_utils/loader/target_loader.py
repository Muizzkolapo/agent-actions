"""Module for target loader."""
import itertools
from pathlib import Path
import json
import os
import copy
import traceback
from agent_actions.agent_utils.transformers.aggregators  import process_as_string
try:
    from agent_actions.agent_utils.agent_builder import agent_builder
    from agent_actions.agent_utils.processor.clean_target import clean_agent_output
    from agent_actions.agent_utils.transformers.aggregators import update_schema_objects,replace_placeholders,transform_structure,replace_guid_placeholder

except ImportError:
    # Handle import error gracefully
    update_schema_objects = None
    replace_placeholders = None
    transform_structure = None
    replace_guid_placeholder = None







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
    new_data = process_data(data, agent_config, agent_name,file_path)
    save_output(new_data, file_path, base_directory, output_directory)

def load_json(file_path):
    """
    Loads JSON data from a given file path.

    :param file_path: Path to the input JSON file
    :return: Parsed JSON data as a list of dictionaries
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


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




def process_data(data, agent_config, agent_name,file_path):
    """
    Processes the input data based on the agent configuration and generates new data.

    :param data: List of dictionaries containing the input data
    :param agent_config: Configuration dictionary for the agent
    :param agent_name: Name of the agent
    :return: List of dictionaries containing the processed data
    """

    # Load the source data for the current file being processed
    file_name = os.path.basename(file_path)
    path = Path(file_path)
    base_path = path.parents[2]
    source_path = os.path.join(base_path, "source",file_name)
    with open(source_path, 'r') as file:
        source_data = json.load(file)


    processed_data = []
    select_list = {agent_config['agent_type']: agent_config['select_list']}
    selection_keys = list(select_list.keys())
    for items in data:
        contents = items['content']
        guid = items['guid']

        # for the provided guid get the source data that generated it at first layer
        source_content = get_content_by_guid(source_data, guid)
        raw_prompt = agent_config['prompt']
        source_loaded_prompt = replace_guid_placeholder(raw_prompt, source_content)
        formated_prompt=replace_placeholders(source_loaded_prompt,contents)


        # Generate dynamic with agent builder but we dont need the returned source in this case
        generated_data = agent_builder.create_dynamic_agent(agent_config, agent_name, contents,formated_prompt)

        if should_update_schema(agent_config, selection_keys, select_list):
            updated_generated_data = []
            for data in generated_data:
                keys_to_update = select_list[agent_config['agent_type']]
                merged_questions = update_schema_objects(contents,
                                                        data,
                                                        keys_to_update)
                
                updated_generated_data.append(merged_questions)
                
            updated_generated_data_response_temp = [{guid: updated_generated_data}]
            updated_transformed_response = transform_structure(updated_generated_data_response_temp) 
            processed_data.extend(updated_transformed_response)
        else:
            transformed_response_temp = [{guid: generated_data}]
            transformed_response = transform_structure(transformed_response_temp) 
            processed_data.extend(transformed_response)


    return processed_data




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






