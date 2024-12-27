import json 
import traceback
import importlib
import os 
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.exceptions import (
    raise_module_import_error,
    raise_function_call_error,
    raise_file_processing_error,
    raise_no_files_found_error
)
import shutil
import random
import logging
import re
import yaml
from agent_actions.logging_setup import setup_logging





class AgentManager:
    """
    A class for managing agent directories and configurations.
    """

    @staticmethod
    def clean_agent_directories(agent_name):
        """
        Deletes all files under the staging, source, and target folders for the specified agent.
        """
        current_dir = os.getcwd()
        agent_folder = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')

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

    @staticmethod
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

    @staticmethod
    def process_and_generate_for_agent(agent_config,
                                       agent_name,
                                       previous_agent_type,
                                       loader,
                                       function_name):
        """
        Processes and generates data for an agent.
        """
        try:
            current_dir = os.getcwd()
            agent_folder = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')

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
                raise_module_import_error(function_name, loader, str(e))

            if not function_call or not callable(function_call):
                raise_function_call_error(function_name, loader)

            files_processed = False
            for root, _, files in os.walk(input_directory):
                if files:
                    files_processed = True
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        function_call(agent_config, agent_name, file_path, input_directory, output_directory)
                    except Exception as e:
                        raise_file_processing_error(file, str(e))

            if not files_processed:
                raise_no_files_found_error(input_directory)

            return output_directory

        except Exception as e:
            raise e

    @staticmethod
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


