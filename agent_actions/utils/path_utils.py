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


def find_project_root(start_path: Path | None = None) -> Path:
    """Find project root by looking for marker file.

    Raises:
        ProjectRootNotFoundError: If project root cannot be found.
    """
    pm = get_path_manager()
    return pm.get_project_root(start_path)


def clean_directory(directory: str | Path, recursive: bool = False) -> bool:
    """Clean/remove a directory."""
    return get_path_manager().clean_path(Path(directory), recursive=recursive)


def get_relative_path(path: str | Path, base: str | Path) -> Path:
    """Get path relative to base directory."""
    abs_path = resolve_absolute_path(path)
    abs_base = resolve_absolute_path(base)
    return abs_path.relative_to(abs_base)


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
