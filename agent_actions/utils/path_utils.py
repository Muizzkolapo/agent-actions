"""
Utility functions for common path operations.

This module provides convenience functions that consolidate the most frequently
duplicated path logic identified across the codebase.
"""

from pathlib import Path
from typing import Optional, Union, Dict, List, Set, TypeVar
import logging
from collections import deque
from agent_actions.config.paths import PathManager

logger = logging.getLogger(__name__)
T = TypeVar("T")
_global_path_manager: Optional[PathManager] = None


def get_path_manager() -> PathManager:
    """
    Get the global PathManager instance.

    Returns:
        Global PathManager instance
    """
    global _global_path_manager  # Singleton pattern
    if _global_path_manager is None:
        _global_path_manager = PathManager()
    return _global_path_manager


def ensure_directory_exists(path: Union[str, Path], is_file: bool = False) -> Path:
    """
    Ensure a directory exists, creating it if necessary.

    This replaces the most common duplicated pattern:
    path.parent.mkdir(parents=True, exist_ok=True)

    Args:
        path: Path to ensure exists
        is_file: If True, ensures parent directory exists for file path

    Returns:
        Resolved path
    """
    return get_path_manager().ensure_path_exists(Path(path), is_file=is_file)


def resolve_absolute_path(path: Union[str, Path]) -> Path:
    """
    Resolve path to absolute Path object.

    This replaces the duplicated pattern:
    resolved_path = str(Path(path).resolve())

    Args:
        path: Path to resolve

    Returns:
        Resolved absolute Path object
    """
    return get_path_manager().normalize_path(path)


def check_path_exists(path: Union[str, Path]) -> bool:
    """
    Check if a path exists.

    This provides a consistent interface for the frequently used:
    path.exists() pattern

    Args:
        path: Path to check

    Returns:
        True if path exists
    """
    return Path(path).exists()


def find_project_root(start_path: Optional[Path] = None) -> Path:
    """
    Find project root by looking for marker file.

    This consolidates the project root discovery logic.

    Args:
        start_path: Starting point for search

    Returns:
        Path to project root

    Raises:
        ProjectRootNotFoundError: If project root cannot be found
    """
    pm = PathManager()
    return pm.get_project_root(start_path)


def create_mirror_source_path(target_path: Union[str, Path]) -> Path:
    """
    Create source path by mirroring target path structure.

    This replaces the complex logic in SourceDataLoader and similar components.

    Args:
        target_path: Original target path

    Returns:
        Mirrored source path
    """
    return get_path_manager().create_mirror_path(Path(target_path), "target", "source")


def validate_path_permissions(
    path: Union[str, Path], readable: bool = False, writable: bool = False
) -> bool:
    """
    Validate path permissions.

    This consolidates the permission checking logic found in validators.

    Args:
        path: Path to validate
        readable: Check if path is readable
        writable: Check if path is writable

    Returns:
        True if path meets all permission requirements
    """
    requirements = {}
    if readable:
        requirements["must_be_readable"] = True
    if writable:
        requirements["must_be_writable"] = True
    try:
        return get_path_manager().validate_path(Path(path), requirements)
    except (PermissionError, OSError, ValueError) as e:
        logger.debug(
            "Path validation failed, returning False: %s",
            e,
            extra={
                "path": str(path),
                "readable": readable,
                "writable": writable,
                "operation": "path_permission_validation",
            },
        )
        return False


def clean_directory(directory: Union[str, Path], recursive: bool = False) -> bool:
    """
    Clean/remove a directory.

    Args:
        directory: Directory to clean
        recursive: Remove contents recursively

    Returns:
        True if successfully cleaned
    """
    return get_path_manager().clean_path(Path(directory), recursive=recursive)


def get_relative_path(path: Union[str, Path], base: Union[str, Path]) -> Path:
    """
    Get path relative to base directory.

    Args:
        path: Absolute path
        base: Base directory

    Returns:
        Path relative to base
    """
    abs_path = resolve_absolute_path(path)
    abs_base = resolve_absolute_path(base)
    return abs_path.relative_to(abs_base)


def find_files_by_extension(directory: Union[str, Path], extension: str) -> list[Path]:
    """
    Find all files with specific extension in directory.

    Args:
        directory: Directory to search
        extension: File extension (with or without dot)

    Returns:
        List of matching file paths
    """
    if not extension.startswith("."):
        extension = f".{extension}"
    pattern = f"**/*{extension}"
    return get_path_manager().find_files_by_pattern(pattern, Path(directory))


def safe_path_join(*parts: Union[str, Path]) -> Path:
    """
    Safely join path parts, ensuring result is within project bounds.

    Args:
        *parts: Path parts to join

    Returns:
        Joined path

    Raises:
        ValueError: If resulting path would be outside project
    """
    joined_path = Path()
    for part in parts:
        joined_path = joined_path / Path(part)
    resolved_path = resolve_absolute_path(joined_path)
    from agent_actions.errors import FileSystemError

    pm = get_path_manager()
    if not pm.is_within_project(resolved_path):
        raise FileSystemError(
            f"Path {resolved_path} is outside project bounds",
            context={
                "resolved_path": str(resolved_path),
                "project_root": str(pm.get_project_root()),
                "operation": "safe_join_paths",
            },
        )
    return resolved_path


def create_agent_directory_structure(agent_name: str) -> dict[str, Path]:
    """
    Create standard agent directory structure.

    This consolidates the agent directory creation logic.
    Directories are created under the project root as resolved by PathManager.

    Args:
        agent_name: Name of the agent

    Returns:
        Dictionary of created directory paths
    """
    pm = get_path_manager()
    agent_paths = pm.get_agent_paths(agent_name)
    created_paths = {}
    for name, path in agent_paths.items():
        created_paths[name] = ensure_directory_exists(path)
    logger.info("Created agent directory structure for %s", agent_name)
    return created_paths


DEFAULT_MARKER_FILE = "agent_actions.yml"
COMMON_EXTENSIONS = [".json", ".yml", ".yaml", ".txt", ".py"]


def topological_sort(dependencies: Dict[T, List[T]]) -> List[T]:
    """
    Perform a topological sort on a dependency graph.

    Consolidated from core_utils.py as part of utilities module reorganization.

    Args:
        dependencies: A dictionary where each key is a node and the value is a list of nodes
                      that the key depends on.

    Returns:
        A list of nodes in topologically sorted order (reversed order for correct processing).

    Raises:
        ValueError: If the dependencies input is invalid or a cyclic dependency is detected.
    """
    if not isinstance(dependencies, dict):
        from agent_actions.errors import DataValidationError

        message = (
            f"Invalid type for dependencies: expected dictionary, got {type(dependencies).__name__}"
        )
        raise DataValidationError(message, context={"operation": "topological_sort"})
    all_nodes = set(dependencies.keys())
    for dependent_nodes in dependencies.values():
        all_nodes.update(dependent_nodes)
    in_degree: Dict[T, int] = {node: 0 for node in all_nodes}
    for node, dependent_nodes in dependencies.items():
        for dep_node in dependent_nodes:
            in_degree[dep_node] += 1
    queue = deque([node for node, degree in in_degree.items() if degree == 0])
    sorted_nodes: List[T] = []
    while queue:
        current = queue.popleft()
        sorted_nodes.append(current)
        if current in dependencies:
            for neighbor in dependencies[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
    if len(sorted_nodes) != len(all_nodes):
        from agent_actions.errors import WorkflowError

        cycle_nodes: Set[T] = all_nodes - set(sorted_nodes)
        message = "Cyclic dependency detected in the workflow"
        raise WorkflowError(
            message,
            context={
                "cycle_nodes": list(cycle_nodes),
                "sorted_nodes": sorted_nodes,
                "all_nodes": list(all_nodes),
                "operation": "dependency_resolution",
            },
        )
    return sorted_nodes[::-1]
