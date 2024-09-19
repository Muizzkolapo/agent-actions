"""Module for target loader."""
from pathlib import Path
import json
import os
import logging
from typing import List, Dict, Any, Tuple
from agent_actions.models import agent_builder
from agent_actions.core.utils import update_schema_objects, replace_placeholders, transform_structure, replace_guid_placeholder,get_agent_paths
from agent_actions.core.agent_handlers import should_update_schema, get_content_by_guid,load_sample_output

# Constants
TOOL_VENDOR = 'tool'
SOURCE_FOLDER = 'source'

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)




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
    
    model_vendor = agent_config.get('model_vendor', '').lower()
    side_output = agent_config.get('side_output', False)
    
    if isinstance(side_output, str):
        side_output = side_output.lower() == 'true'
    
    if model_vendor == 'tool' and side_output:
        main_output, side_output_data = process_data_for_side_output(data, agent_config, agent_name, file_path)
        save_output(main_output, file_path, base_directory, output_directory)
        
        if side_output_data:
            side_output_directory = output_directory
            save_side_output(side_output_data, file_path, base_directory, side_output_directory)
    else:
        new_data = process_data(data, agent_config, agent_name, file_path)
        save_output(new_data, file_path, base_directory, output_directory)


def load_json(file_path):
    """
    Loads JSON data from a given file path.

    :param file_path: Path to the input JSON file
    :return: Parsed JSON data as a list of dictionaries
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)





#==============================================================process data ==================================================================================

def process_data(data: List[Dict[str, Any]], agent_config: Dict[str, Any], agent_name: str, file_path: str) -> List[Dict[str, Any]]:
    try:
        source_data = load_source_data(file_path)
        processed_data = []
        side_collection = agent_config.get('side_collection', [])
        selection_keys = [agent_config['agent_type']]

        for items in data:
            try:
                processed_item = process_single_item(items, agent_config, agent_name, source_data, side_collection, selection_keys)
                processed_data.extend(processed_item)
            except Exception as e:
                logger.error(f"Error processing item: {e}")

        return processed_data
    except Exception as e:
        logger.error(f"Error in process_data: {e}")
        raise

def process_data_for_side_output(data: List[Dict[str, Any]], agent_config: Dict[str, Any], agent_name: str, file_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    try:
        source_data = load_source_data(file_path)
        main_output = []
        side_output = []
        side_collection = agent_config.get('side_collection', [])
        selection_keys = [agent_config['agent_type']]

        for item in data:
            try:
                processed_item = process_single_item(item, agent_config, agent_name, source_data, side_collection, selection_keys)
                if isinstance(processed_item, list):
                    for sub_item in processed_item:
                        content = sub_item.get('content', {})
                        if isinstance(content, dict):
                            if content.get('side_output', False):
                                side_output.append(sub_item)
                            else:
                                main_output.append(sub_item)
                        else:
                            logger.warning(f"Unexpected content format: {content}")
                else:
                    logger.warning(f"Unexpected item format: {processed_item}")
            except Exception as e:
                logger.error(f"Error processing item: {str(e)}")

        return main_output, side_output
    except Exception as e:
        logger.error(f"Error in process_data_for_side_output: {str(e)}")
        raise

def process_single_item(item: Dict[str, Any], agent_config: Dict[str, Any], agent_name: str, source_data: List[Dict[str, Any]], side_collection: List[str], selection_keys: List[str]) -> List[Dict[str, Any]]:
    contents = item['content']
    guid = item['guid']
    source_content = get_content_by_guid(source_data, guid)

    generated_data = generate_data(agent_config, agent_name, contents, source_content)
    return process_item(agent_config, contents, generated_data, guid, side_collection, selection_keys)

#================================================================================================================================================




def load_source_data(file_path):
    """Load source data from the corresponding file."""
    file_name = os.path.basename(file_path)
    path = Path(file_path)
    base_path = path.parents[2]
    source_path = os.path.join(base_path, "source", file_name)
    with open(source_path, 'r') as file:
        return json.load(file)







def generate_data2(agent_config, agent_name, contents, source_content):
    """Generate data using the appropriate method based on the agent configuration."""
    if agent_config['model_vendor'].lower() == 'tool':
        return agent_builder.create_dynamic_agent(agent_config, agent_name, contents)
    else:
        raw_prompt = agent_config.get('prompt', '')
        source_loaded_prompt = replace_guid_placeholder(raw_prompt, str(source_content))
        formatted_prompt = replace_placeholders(source_loaded_prompt, contents)
        return agent_builder.create_dynamic_agent(agent_config, agent_name, contents, formatted_prompt)




#=====================================================to be reviewed===========================================================================================
def generate_data(agent_config, agent_name, contents, source_content):
    """
    Generate data using the appropriate method based on the agent configuration,
    incorporating sample outputs if specified.
    """

    # Load the sample output path using get_agent_paths
    try:
        _, _, sample_output_path = get_agent_paths(agent_name)
    except FileNotFoundError as e:
        logger.error(f"Error finding sample output path: {e}")
        sample_output_path = None

    # Retrieve the sample count from the agent configuration
    sample_count = agent_config.get("use_sample_output", 0)
    try:
        sample_count = int(sample_count)
    except ValueError:
        logger.warning("use_sample_output is not an integer. Defaulting to 0.")
        sample_count = 0

    # Check if sample_count is a positive integer and sample_output_path is valid
    if sample_count > 0 and sample_output_path:
        logger.info(f"Loading {sample_count} sample outputs.")
        samples = load_sample_output(
            sample_output_path,
            sample_count=sample_count
        )
        # Append samples to contents as a new key
        if isinstance(contents, dict):
            contents['samples'] = samples
        else:
            logger.warning("Contents is not a dictionary. Cannot add samples.")
    else:
        logger.info("Not using sample outputs.")

    # Now proceed with data generation
    if agent_config['model_vendor'].lower() == 'tool':
        return agent_builder.create_dynamic_agent(agent_config, agent_name, contents)
    else:
        raw_prompt = agent_config.get('prompt', '')
        source_loaded_prompt = replace_guid_placeholder(raw_prompt, str(source_content))
        formatted_prompt = replace_placeholders(source_loaded_prompt, contents)
        return agent_builder.create_dynamic_agent(agent_config, agent_name, contents, formatted_prompt)


#================================================================================================================================================






def process_item(agent_config, contents, generated_data, guid, side_collection, selection_keys):
    """Process a single item and return the transformed response."""
    if should_update_schema(agent_config, selection_keys, {agent_config['agent_type']: side_collection}):
        updated_generated_data = [
            update_schema_objects(contents, data_item, side_collection)
            for data_item in generated_data
        ]
        response_temp = [{guid: updated_generated_data}]
    else:
        response_temp = [{guid: generated_data}]
    
    return transform_structure(response_temp)








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


"""def save_side_output(side_output_data, file_path, base_directory, output_directory):
    relative_path = os.path.relpath(file_path, base_directory)
    side_output_dir = os.path.join(output_directory, 'side_output')
    side_output_file_path = os.path.join(side_output_dir, relative_path)
    os.makedirs(os.path.dirname(side_output_file_path), exist_ok=True)
    with open(side_output_file_path, 'w', encoding='utf-8') as file:
        json.dump(side_output_data, file, indent=4)"""
def save_side_output(side_output_data, file_path, base_directory, output_directory):
    """
    Saves the side output data to a 'side_output' directory at the same level as the output directory.

    :param side_output_data: List of dictionaries containing the side output data
    :param file_path: Path to the input JSON file
    :param base_directory: Base directory for calculating relative paths
    :param output_directory: Directory where the main output is saved
    """
    relative_path = os.path.relpath(file_path, base_directory)
    side_output_dir = os.path.join(os.path.dirname(output_directory), 'side_output')
    side_output_file_path = os.path.join(side_output_dir, os.path.basename(relative_path))
    os.makedirs(os.path.dirname(side_output_file_path), exist_ok=True)

    # If the file exists, load its current contents
    if os.path.exists(side_output_file_path):
        with open(side_output_file_path, 'r', encoding='utf-8') as file:
            try:
                existing_content = json.load(file)
            except json.JSONDecodeError:
                existing_content = []
    else:
        existing_content = []

    # Ensure existing content is a list
    if not isinstance(existing_content, list):
        existing_content = [existing_content]

    # Append new side output data
    existing_content.extend(side_output_data)

    # Write back to the file
    with open(side_output_file_path, 'w', encoding='utf-8') as file:
        json.dump(existing_content, file, indent=4)


