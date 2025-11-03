"""Module for staging data loading and processing."""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

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
                return str(Path(root) / target_filename)
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
                target_folder_path = Path(root) / parent_folder_name / folder_name
                if target_folder_path.is_dir():
                    return str(target_folder_path)
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
        base_path = Path(working_directory) / base_dir
        for root, dirs, _ in os.walk(str(base_path)):
            if folder_name in dirs:
                return str(Path(root) / folder_name)
        return None

    @staticmethod
    def get_agent_paths(agent_name):
        """
        Returns the agent configuration directory, IO directory, and sample output path.

        Parameters:
            agent_name (str): The name of the agent.

        Returns:
            tuple: (agent_config_dir, io_dir, few_shot_samples_path)
        """
        current_dir = Path.cwd()
        agent_config_dir = FileHandler.find_specific_folder(
            str(current_dir), agent_name, 'agent_config'
        )
        io_dir = FileHandler.find_specific_folder(
            str(current_dir), agent_name, 'agent_io'
        )

        few_shot_samples_path = None
        if io_dir:
            potential_path = Path(io_dir) / 'few_shot_samples'
            if potential_path.exists():
                few_shot_samples_path = str(potential_path)
            else:
                logger.warning(
                    "Few shot samples folder not found at %s", potential_path
                )

        return agent_config_dir, io_dir, few_shot_samples_path

    @staticmethod
    def find_config_file(base_dir, filename):
        """
        Recursively searches for a configuration file in the base directory and its parents.

        Parameters:
            base_dir (str): The directory to start searching from.
            filename (str): The name of the configuration file.

        Returns:
            str or None: The path to the configuration file if found.
        """
        for root, _, files in os.walk(base_dir):
            if filename in files:
                return str(Path(root) / filename)

        parent_dir = Path(base_dir).parent
        if parent_dir != Path(base_dir):  # Ensure we're not at the root
            return FileHandler.find_config_file(str(parent_dir), filename)

        print(f"Config file '{filename}' not found in {base_dir} or its parent directories.")
        return None

    @staticmethod
    def get_folder_after_agent_config(path):
        """
        Extracts the folder name immediately following 'agent_config' in a path.

        Parameters:
            path (str): The file path to analyze.

        Returns:
            str or None: The folder name following 'agent_config' or None if not found.
        """
        path_components = Path(path).parts

        if 'agent_config' in path_components:
            agent_config_index = path_components.index('agent_config')

            if agent_config_index + 1 == len(path_components) - 1 and Path(path).is_file():
                return '(isfile)'

            if agent_config_index + 1 < len(path_components):
                return path_components[agent_config_index + 1]

        return None

    @staticmethod
    def get_folder(agent_name):
        """
        Gets the folder name and full path for an agent's configuration.

        Parameters:
            agent_name (str): The name of the agent.

        Returns:
            tuple: (folder_name, full_path) or (None, None) if not found.
        """
        agent_config_dir = Path.cwd() / 'agent_config'
        filename = f"{agent_name}.yml" if not agent_name.endswith(".yml") else agent_name
        full_path = FileHandler.find_config_file(str(agent_config_dir), filename)
        return FileHandler.get_folder_after_agent_config(full_path), full_path

    @staticmethod
    def get_all_agent_paths(base_dir):
        """
        Gets all agent configuration file paths within the base directory.

        Parameters:
            base_dir (str): The base directory to search in.

        Returns:
            list: A list of paths to agent configuration files.
        """
        agent_paths = []
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith(".yml"):
                    agent_paths.append(str(Path(root) / file))
        return agent_paths

    @staticmethod
    def get_file_info(file_path):
        """
        Gets information about a file in the staging directory.

        Parameters:
            file_path (str): The file path in the staging directory.

        Returns:
            str: The source file path or an error message.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return f"File '{file_path}' does not exist."

        dir_path = file_path.parent
        agent_dir = dir_path.parent
        source_path = agent_dir / 'source'
        source_file_path = source_path / file_path.name

        if source_path.exists():
            return str(source_file_path)
        return None
