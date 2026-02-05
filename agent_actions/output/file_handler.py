"""
Shared file and directory operations utilities.
"""

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
    def get_agent_paths(agent_name):
        """
        Returns the agent configuration directory and IO directory.

        Parameters:
            agent_name (str): The name of the agent.

        Returns:
            tuple: (agent_config_dir, io_dir)
        """
        current_dir = Path.cwd()
        agent_config_dir = FileHandler.find_specific_folder(
            str(current_dir), agent_name, "agent_config"
        )
        io_dir = FileHandler.find_specific_folder(str(current_dir), agent_name, "agent_io")
        return agent_config_dir, io_dir

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

        logger.warning("Config file '%s' not found in %s or its parent directories.", filename, base_dir)
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

        if "agent_config" in path_components:
            agent_config_index = path_components.index("agent_config")

            if agent_config_index + 1 == len(path_components) - 1 and Path(path).is_file():
                return "(isfile)"

            if agent_config_index + 1 < len(path_components):
                return path_components[agent_config_index + 1]

        return None

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

