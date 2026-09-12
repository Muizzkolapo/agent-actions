"""
Shared file and directory operations utilities.
"""

import logging
import os
from pathlib import Path

from agent_actions.config.path_config import resolve_project_root

logger = logging.getLogger(__name__)

# Directory names that never hold a user's workflow, prompt or config.
_NON_PROJECT_DIRS = frozenset({".git", "node_modules", "__pycache__"})


def prune_non_project_dirs(root: str, dirs: list[str]) -> None:
    """Drop directories a project search must not descend into, in place.

    A virtualenv is identified by its ``pyvenv.cfg`` rather than by name, so
    any of ``.venv``/``venv``/``env`` is caught. These trees dwarf the project
    itself, and a dependency's file matching the searched name would otherwise
    win or lose by filesystem order.
    """
    dirs[:] = [
        d
        for d in dirs
        if d not in _NON_PROJECT_DIRS and not (Path(root) / d / "pyvenv.cfg").is_file()
    ]


class FileHandler:
    """Utilities for file and directory path discovery."""

    @staticmethod
    def find_file_in_directory(directory, target_filename):
        """Recursively search for a file by name, returning its full path or None."""
        for root, dirs, files in os.walk(directory):
            prune_non_project_dirs(root, dirs)
            if target_filename in files:
                return str(Path(root) / target_filename)
        return None

    @staticmethod
    def find_specific_folder(current_dir, parent_folder_name, folder_name):
        """Find a subfolder under a named parent folder, returning its full path or None."""
        for root, dirs, _ in os.walk(current_dir):
            prune_non_project_dirs(root, dirs)
            if parent_folder_name in dirs:
                target_folder_path = Path(root) / parent_folder_name / folder_name
                if target_folder_path.is_dir():
                    return str(target_folder_path)
        return None

    @staticmethod
    def find_all_specific_folders(current_dir, parent_folder_name, folder_name):
        """Return every matching folder path under a named parent folder (empty if none)."""
        matches = []
        for root, dirs, _ in os.walk(current_dir):
            prune_non_project_dirs(root, dirs)
            if parent_folder_name in dirs:
                target_folder_path = Path(root) / parent_folder_name / folder_name
                if target_folder_path.is_dir():
                    matches.append(str(target_folder_path))
        return matches

    @staticmethod
    def get_agent_paths(agent_name, project_root: Path | None = None):
        """Return (agent_config_dir, io_dir), raising when the agent name is ambiguous."""
        from agent_actions.errors.validation import AmbiguousAgentName

        search_dir = resolve_project_root(project_root)
        config_matches = FileHandler.find_all_specific_folders(
            str(search_dir), agent_name, "agent_config"
        )
        if len(config_matches) >= 2:
            raise AmbiguousAgentName(agent_name, config_matches)
        agent_config_dir = config_matches[0] if config_matches else None
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
    def get_all_agent_paths(base_dir):
        """Return all .yml file paths found recursively under base_dir."""
        agent_paths = []
        for root, dirs, files in os.walk(base_dir):
            prune_non_project_dirs(root, dirs)
            for file in files:
                if file.endswith(".yml"):
                    agent_paths.append(str(Path(root) / file))
        return agent_paths
