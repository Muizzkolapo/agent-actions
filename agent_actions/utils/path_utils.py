"""Convenience functions for common path operations."""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from agent_actions.config.paths import PathManager

logger = logging.getLogger(__name__)
T = TypeVar("T")
_global_path_manager: PathManager | None = None


def get_path_manager() -> PathManager:
    """Get the global PathManager singleton."""
    from agent_actions.config.paths import PathManager

    global _global_path_manager
    if _global_path_manager is None:
        _global_path_manager = PathManager()
    return _global_path_manager


def ensure_directory_exists(path: str | Path, is_file: bool = False) -> Path:
    """Ensure a directory exists, creating it if necessary."""
    return get_path_manager().ensure_path_exists(Path(path), is_file=is_file)


def resolve_absolute_path(path: str | Path) -> Path:
    """Resolve path to an absolute Path object."""
    return get_path_manager().normalize_path(path)


def check_path_exists(path: str | Path) -> bool:
    """Check if a path exists."""
    return Path(path).exists()


def find_project_root(start_path: Path | None = None) -> Path:
    """Find project root by looking for marker file.

    Raises:
        ProjectRootNotFoundError: If project root cannot be found.
    """
    pm = get_path_manager()
    return pm.get_project_root(start_path)


def create_mirror_source_path(target_path: str | Path) -> Path:
    """Create a source path by mirroring the target path structure."""
    return get_path_manager().create_mirror_path(Path(target_path), "target", "source")


def validate_path_permissions(
    path: str | Path, readable: bool = False, writable: bool = False
) -> bool:
    """Validate path permissions, returning False on failure."""
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


def clean_directory(directory: str | Path, recursive: bool = False) -> bool:
    """Clean/remove a directory."""
    return get_path_manager().clean_path(Path(directory), recursive=recursive)


def get_relative_path(path: str | Path, base: str | Path) -> Path:
    """Get path relative to base directory."""
    abs_path = resolve_absolute_path(path)
    abs_base = resolve_absolute_path(base)
    return abs_path.relative_to(abs_base)


def find_files_by_extension(directory: str | Path, extension: str) -> list[Path]:
    """Find all files with the given extension in directory (recursive)."""
    if not extension.startswith("."):
        extension = f".{extension}"
    pattern = f"**/*{extension}"
    return get_path_manager().find_files_by_pattern(pattern, Path(directory))


def safe_path_join(*parts: str | Path) -> Path:
    """Join path parts, raising FileSystemError if result is outside the project."""
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
    """Create the standard agent directory structure under the project root."""
    pm = get_path_manager()
    agent_paths = pm.get_agent_paths(agent_name)
    created_paths = {}
    for name, path in agent_paths.items():
        created_paths[name] = ensure_directory_exists(path)
    logger.info("Created agent directory structure for %s", agent_name)
    return created_paths


DEFAULT_MARKER_FILE = "agent_actions.yml"
COMMON_EXTENSIONS = [".json", ".yml", ".yaml", ".txt", ".py"]


def topological_sort(dependencies: dict[T, list[T]]) -> list[T]:
    """Topologically sort a dependency graph, returning nodes in processing order.

    Raises:
        DataValidationError: If input is invalid.
        WorkflowError: If a cyclic dependency is detected.
    """
    if not isinstance(dependencies, dict):
        from agent_actions.errors import DataValidationError  # type: ignore[unreachable]

        message = (
            f"Invalid type for dependencies: expected dictionary, got {type(dependencies).__name__}"
        )
        raise DataValidationError(message, context={"operation": "topological_sort"})
    all_nodes = set(dependencies.keys())
    for dependent_nodes in dependencies.values():
        all_nodes.update(dependent_nodes)
    in_degree: dict[T, int] = {node: 0 for node in all_nodes}
    for _node, dependent_nodes in dependencies.items():
        for dep_node in dependent_nodes:
            in_degree[dep_node] += 1
    queue = deque([node for node, degree in in_degree.items() if degree == 0])
    sorted_nodes: list[T] = []
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

        cycle_nodes: set[T] = all_nodes - set(sorted_nodes)
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
