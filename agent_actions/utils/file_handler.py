"""
Shared file and directory operations utilities.
"""

import logging
import os
from pathlib import Path

from agent_actions.config.path_config import resolve_project_root

logger = logging.getLogger(__name__)


class FileHandler:
    """Utilities for file and directory path discovery."""

    @staticmethod
    def find_file_in_directory(directory, target_filename):
        """Recursively search for a file by name, returning its full path or None."""
        for root, _, files in os.walk(directory):
            if target_filename in files:
                return str(Path(root) / target_filename)
        return None

    @staticmethod
    def find_specific_folder(current_dir, parent_folder_name, folder_name):
        """Find a subfolder under a named parent folder, returning its full path or None."""
        for root, dirs, _ in os.walk(current_dir):
            if parent_folder_name in dirs:
                target_folder_path = Path(root) / parent_folder_name / folder_name
                if target_folder_path.is_dir():
                    return str(target_folder_path)
        return None

    @staticmethod
    def get_agent_paths(agent_name, project_root: Path | None = None):
        """Return (agent_config_dir, io_dir) for the given agent name."""
        search_dir = resolve_project_root(project_root)
        agent_config_dir = FileHandler.find_specific_folder(
            str(search_dir), agent_name, "agent_config"
        )
        io_dir = FileHandler.find_specific_folder(str(search_dir), agent_name, "agent_io")
        return agent_config_dir, io_dir

    @staticmethod
    def find_config_file(base_dir, filename):
        """Search for a config file in base_dir and its parent directories.

        Checks each directory (without recursing into subdirectories) by
        walking up the parent chain using ``Path.parents``.
        """
        base = Path(base_dir).resolve()
        for directory in (base, *base.parents):
            candidate = directory / filename
            if candidate.is_file():
                return str(candidate)
            # Stop at filesystem root to avoid matching unrelated files
            if directory == directory.parent:
                break

        logger.warning(
            "Config file '%s' not found in %s or its parent directories.", filename, base_dir
        )
        return None

    @staticmethod
    def get_folder_after_agent_config(path):
        """Extract the folder name immediately following 'agent_config' in a path.

        Returns '(isfile)' when the next component is a file, None if 'agent_config' is absent.
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
        """Return all .yml file paths found recursively under base_dir."""
        agent_paths = []
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith(".yml"):
                    agent_paths.append(str(Path(root) / file))
        return agent_paths
