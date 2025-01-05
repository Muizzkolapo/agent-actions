import json 
import os 
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.exceptions import (
    raise_file_processing_error,
    raise_no_files_found_error
)
import shutil




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

        source_dir = os.path.join(agent_folder, 'source')
        target_dir = os.path.join(agent_folder, 'target')

        for directory in [source_dir, target_dir]:
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






