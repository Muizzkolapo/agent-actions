"""Project root detection utilities."""

import os
from pathlib import Path

from agent_actions.errors import ProjectNotFoundError

PROJECT_MARKER_FILE = "agent_actions.yml"
MAX_PARENT_LEVELS = 100


def find_project_root(start_path: str | None = None) -> Path | None:
    """Walk up from start_path (or cwd) looking for agent_actions.yml."""
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
    """Return the project root or raise ProjectNotFoundError."""
    project_root = find_project_root()
    if project_root is None:
        raise ProjectNotFoundError(
            "Project not found",
            context={"marker_file": PROJECT_MARKER_FILE, "search_path": os.getcwd()},
        )
    return project_root
