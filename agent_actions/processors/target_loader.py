"""Module for target loader."""
import json
import os
from agent_actions.handlers.file_handler import FileReader, FileWriter  
from agent_actions.processors.target_content import TargetContentProcessor
from agent_actions.exceptions import (
    raise_target_processing_error,
    raise_target_save_error,
    raise_side_output_error
)

TOOL_VENDOR = 'tool'
SOURCE_FOLDER = 'source'

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
    try:
        file_reader = FileReader(file_path)
        data = file_reader.read()

        model_vendor = agent_config.get('model_vendor', '').lower()
        granularity = agent_config.get('granularity', '').lower()
        side_output = agent_config.get('side_output', False)

        content_processor = TargetContentProcessor(agent_config, agent_name)

        if model_vendor == 'tool' and granularity == 'record' and side_output:
            try:
                main_output, side_output_data = content_processor.process_for_side_output(data, file_path)
                save_output(main_output, file_path, base_directory, output_directory)

                if side_output_data:
                    side_output_directory = output_directory
                    save_side_output(side_output_data, file_path, base_directory, side_output_directory)
            except Exception as e:
                raise_side_output_error(file_path, str(e))

        elif model_vendor == 'tool' and granularity=='file':
            try:
                main_output = content_processor.process_file_level(data)
                save_output(main_output, file_path, base_directory, output_directory)
            except Exception as e:
                raise_target_processing_error(file_path, str(e))

        elif granularity == 'record':
            try:
                new_data = content_processor.process(data, file_path)
                save_output(new_data, file_path, base_directory, output_directory)
            except Exception as e:
                raise_target_processing_error(file_path, str(e))

    except Exception as e:
        raise_target_processing_error(file_path, str(e))

def save_output(new_data, file_path, base_directory, output_directory):
    """
    Saves the processed data to the specified output directory.

    :param new_data: List of dictionaries containing the processed data
    :param file_path: Path to the input JSON file
    :param base_directory: Base directory for calculating relative paths
    :param output_directory: Directory where the output file will be saved.
    """
    try:
        relative_path = os.path.relpath(file_path, base_directory)
        output_file_path = os.path.join(output_directory, relative_path)
        file_writer = FileWriter(output_file_path)
        file_writer.write_target(new_data)
    except Exception as e:
        raise_target_save_error(output_file_path, str(e))

def save_side_output(side_output_data, file_path, base_directory, output_directory):
    """
    Saves the side output data to a 'side_output' directory at the same level as the output directory.

    :param side_output_data: List of dictionaries containing the side output data
    :param file_path: Path to the input JSON file
    :param base_directory: Base directory for calculating relative paths
    :param output_directory: Directory where the main output is saved
    """
    try:
        relative_path = os.path.relpath(file_path, base_directory)
        side_output_dir = os.path.join(os.path.dirname(output_directory), 'side_output')
        side_output_file_path = os.path.join(side_output_dir, os.path.basename(relative_path))
        os.makedirs(os.path.dirname(side_output_file_path), exist_ok=True)

        if os.path.exists(side_output_file_path):
            with open(side_output_file_path, 'r', encoding='utf-8') as file:
                try:
                    existing_content = json.load(file)
                except json.JSONDecodeError:
                    existing_content = []
        else:
            existing_content = []

        if not isinstance(existing_content, list):
            existing_content = [existing_content]

        existing_content.extend(side_output_data)

        with open(side_output_file_path, 'w', encoding='utf-8') as file:
            json.dump(existing_content, file, indent=4)
    except Exception as e:
        raise_side_output_error(side_output_file_path, str(e))