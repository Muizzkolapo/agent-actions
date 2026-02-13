"""
Project root detection utilities.

Provides functionality to locate the project root by searching for
agent_actions.yml marker file in the current directory and parent directories.
"""

from pathlib import Path
import os
from typing import Optional
from agent_actions.errors import ProjectNotFoundError

PROJECT_MARKER_FILE = "agent_actions.yml"
MAX_PARENT_LEVELS = 100


def find_project_root(start_path: Optional[str] = None) -> Optional[Path]:
    """
    Find the project root by walking up directories to locate agent_actions.yml.

    Starts from the given path (or current working directory) and walks up
    the directory tree until it finds agent_actions.yml or reaches the
    filesystem root.

    Args:
        start_path: Starting directory (defaults to current working directory)

    Returns:
        Path object pointing to project root, or None if not found

    Examples:
        >>> find_project_root("/projects/my-agents/src/utils")
        Path("/projects/my-agents")  # Found agent_actions.yml here

        >>> find_project_root("/tmp")
        None  # Not in a project

    Notes:
        - Resolves symlinks using Path.resolve()
        - Stops after MAX_PARENT_LEVELS to prevent infinite loops
        - Handles permission errors gracefully
    """
    current = Path(start_path or os.getcwd()).resolve()
    for i, directory in enumerate([current, *current.parents]):
        if i >= MAX_PARENT_LEVELS:
            break
        marker = directory / PROJECT_MARKER_FILE
        try:
            if marker.exists() and marker.is_file():
                return directory
        except PermissionError:
            continue
    return None


def ensure_in_project() -> Path:
    """
    Ensure the current working directory is within an agent-actions project.

    Returns:
        Path to project root

    Raises:
        ProjectNotFoundError: If not in a project

    Example:
        >>> project_root = ensure_in_project()
        >>> os.chdir(project_root)  # Change to project root
    """
    project_root = find_project_root()
    if project_root is None:
        raise ProjectNotFoundError(
            "Project not found",
            context={"marker_file": PROJECT_MARKER_FILE, "search_path": os.getcwd()},
        )
    return project_root
