"""Convenience functions for common path operations."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.config.paths import PathManager

logger = logging.getLogger(__name__)
_global_path_manager: PathManager | None = None
_path_manager_lock = threading.Lock()


def get_path_manager() -> PathManager:
    """Get the global PathManager singleton (thread-safe)."""
    from agent_actions.config.paths import PathManager

    global _global_path_manager
    if _global_path_manager is None:
        with _path_manager_lock:
            if _global_path_manager is None:
                _global_path_manager = PathManager()
    return _global_path_manager


def set_path_manager(pm: PathManager) -> None:
    """Install a specific PathManager as the global instance.

    Use this to inject a PathManager scoped to a known project root
    instead of relying on lazy CWD-based detection.

    Must be called before any concurrent ``get_path_manager()`` calls
    for the new value to be reliably visible (the fast-path read at
    line 25 is outside the lock).
    """
    global _global_path_manager
    with _path_manager_lock:
        _global_path_manager = pm


def reset_path_manager() -> None:
    """Reset the global PathManager instance (for testing).

    Must be called from a single thread (e.g. a serial test fixture),
    not concurrently with ``get_path_manager()``.
    """
    global _global_path_manager
    with _path_manager_lock:
        _global_path_manager = None


def resolve_relative_to(path: str | Path, base: Path) -> Path:
    """Resolve *path* against *base* only when it is relative.

    If *path* is already absolute it is returned as-is; otherwise
    ``base / path`` is returned.  This avoids the common bug where
    ``Path.__truediv__`` silently discards the left operand when the
    right operand is absolute, producing doubled or wrong paths.
    """
    p = Path(path)
    return p if p.is_absolute() else base / p


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


def derive_workflow_root(target_path: str | Path) -> Path:
    """Find workflow root from a path expected to be inside a workflow.

    Strategy:
    1. Fast path — find 'agent_io' in path parts and truncate there.
    2. Walk up looking for a directory containing 'agent_config/' (workflow root marker).
    3. Fallback — return target_path itself with a warning (never blindly chain .parent).
    """
    path = Path(target_path)
    parts = path.parts
    if "agent_io" in parts:
        idx = parts.index("agent_io")
        if idx > 0:
            return Path(*parts[:idx])
    # Walk up looking for agent_config/ sibling
    current = path.resolve()
    while current != current.parent:
        if (current / "agent_config").is_dir():
            return current
        current = current.parent
    logger.warning("Could not determine workflow root from path: %s", target_path)
    return path if path.is_dir() else path.parent
