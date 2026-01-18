"""Centralized module loading utility for UDF discovery and dynamic imports.

This module provides a thread-safe, cached, and testable approach to loading
user-defined functions (UDFs) and managing sys.path modifications.

Architecture:
    High-Level API → discover_and_load_udfs_recursive()
                          ↓
    Mid-Level API →  load_module_from_path()
                          ↓
    Low-Level API →  ensure_path_importable()
                          ↓
                    sys.path (when needed)

Usage Examples:
    # Low-level: Ensure a path is importable
    ensure_path_importable("/path/to/user/code")

    # Mid-level: Load a specific module
    module = load_module_from_path("my_module", "/path/to/module.py")

    # High-level: Discover and load all UDFs
    registry = discover_and_load_udfs_recursive("/path/to/user/code")

Thread Safety:
    All functions are thread-safe using a reentrant lock (RLock).
    Concurrent calls to add paths or load modules are properly synchronized.

Caching:
    - Path cache: Prevents redundant sys.path insertions
    - Module cache: Prevents re-execution of already loaded modules
    - Cache invalidation: Use clear_*_cache() functions (testing only)
"""

import importlib
import importlib.util
import logging
import sys
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)

# Thread-safe caches
_LOCK = threading.RLock()
_PATH_CACHE: Set[str] = set()
_MODULE_CACHE: Dict[str, Any] = {}


# ==============================================================================
# Low-Level API: Path Management
# ==============================================================================


def ensure_path_importable(path: Union[str, Path], *, recursive: bool = False) -> bool:
    """Ensure a path is in sys.path for imports (thread-safe, cached).

    Args:
        path: Directory path to add to sys.path
        recursive: If True, also add all subdirectories (for nested packages)

    Returns:
        True if path was added, False if already present

    Example:
        >>> ensure_path_importable("/path/to/user/code")
        True  # Path was added
        >>> ensure_path_importable("/path/to/user/code")
        False  # Already in cache

    Note:
        Uses absolute() instead of resolve() to maintain backward compatibility
        with existing code that may rely on symlink preservation.
    """
    path_str = str(Path(path).absolute())

    with _LOCK:
        # Check cache first (faster than sys.path lookup)
        if path_str in _PATH_CACHE:
            return False

        # Add to sys.path if not already present
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            logger.debug(f"Added to sys.path: {path_str}")

        # Update cache
        _PATH_CACHE.add(path_str)

    # Handle recursive subdirectories
    if recursive:
        path_obj = Path(path)
        if path_obj.is_dir():
            for subdir in path_obj.rglob("*"):
                if subdir.is_dir() and not subdir.name.startswith("_"):
                    # Recursive call (will check cache)
                    ensure_path_importable(subdir, recursive=False)

    return True


def ensure_paths_importable(paths: List[Union[str, Path]], *, recursive: bool = False) -> int:
    """Ensure multiple paths are in sys.path (thread-safe, cached).

    Args:
        paths: List of directory paths to add
        recursive: If True, also add subdirectories for each path

    Returns:
        Number of new paths added (excluding already cached)

    Example:
        >>> paths = ["/path/one", "/path/two"]
        >>> count = ensure_paths_importable(paths)
        >>> print(f"Added {count} new paths")
    """
    added_count = 0
    for path in paths:
        if ensure_path_importable(path, recursive=recursive):
            added_count += 1
    return added_count


@contextmanager
def importable_path(path: Union[str, Path], *, recursive: bool = False):
    """Context manager for temporary sys.path modification (testing only).

    Args:
        path: Directory path to temporarily add
        recursive: If True, also add subdirectories

    Yields:
        The resolved path string

    Example:
        >>> with importable_path("/tmp/test_code"):
        ...     import my_test_module
        # /tmp/test_code removed from sys.path after context

    Note:
        This does NOT use the cache (for testing isolation).
        In production, prefer ensure_path_importable().
    """
    path_str = str(Path(path).absolute())
    paths_to_remove = []

    try:
        # Add main path
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            paths_to_remove.append(path_str)

        # Add subdirectories if recursive
        if recursive:
            path_obj = Path(path)
            if path_obj.is_dir():
                for subdir in path_obj.rglob("*"):
                    if subdir.is_dir() and not subdir.name.startswith("_"):
                        subdir_str = str(subdir.absolute())
                        if subdir_str not in sys.path:
                            sys.path.insert(0, subdir_str)
                            paths_to_remove.append(subdir_str)

        yield path_str

    finally:
        # Remove paths in reverse order
        for p in paths_to_remove:
            try:
                sys.path.remove(p)
            except ValueError:
                pass  # Already removed


def clear_path_cache() -> None:
    """Clear the path cache (testing only).

    Note:
        This does NOT modify sys.path itself.
        Only clears the internal cache tracking what was added.
    """
    with _LOCK:
        _PATH_CACHE.clear()
        logger.debug("Cleared path cache")


# ==============================================================================
# Mid-Level API: Module Loading
# ==============================================================================


def load_module_from_path(
    module_name: str,
    module_path: Optional[Union[str, Path]] = None,
    *,
    execute: bool = True,
    fallback_import: bool = True,
    cache: bool = True,
) -> Optional[Any]:
    """Load a module from a file path or standard import (thread-safe, cached).

    Args:
        module_name: Name of the module (e.g., "my_module")
        module_path: Optional path to .py file or directory containing module
        execute: If True, execute the module (triggers decorators)
        fallback_import: If True, try standard import if path load fails
        cache: If True, return cached module on subsequent calls

    Returns:
        The loaded module object, or None if loading failed

    Example:
        >>> # Load from path
        >>> module = load_module_from_path("validators", "/path/to/validators.py")

        >>> # Load with fallback to standard import
        >>> module = load_module_from_path("json", fallback_import=True)

        >>> # Load without execution (inspect only)
        >>> module = load_module_from_path("config", execute=False)

    Note:
        Modules are registered in sys.modules BEFORE execution to ensure
        decorator side effects (e.g., @udf_tool, @reprompt_validation) work correctly.
    """
    cache_key = f"{module_name}:{module_path}" if module_path else module_name

    # Thread-safe cache check and load operation
    with _LOCK:
        # Check cache first
        if cache and cache_key in _MODULE_CACHE:
            logger.debug(f"Returning cached module: {module_name}")
            return _MODULE_CACHE[cache_key]

        module = None

        # Try loading from path if provided
        if module_path:
            try:
                module_path_obj = Path(module_path)

                # Handle directory path (look for __init__.py or module_name.py)
                if module_path_obj.is_dir():
                    init_file = module_path_obj / "__init__.py"
                    module_file = module_path_obj / f"{module_name}.py"

                    if init_file.exists():
                        module_path_obj = init_file
                    elif module_file.exists():
                        module_path_obj = module_file
                    else:
                        logger.warning(f"No valid module file found in {module_path}")
                        module_path_obj = None

                # Load from file
                if module_path_obj and module_path_obj.is_file():
                    spec = importlib.util.spec_from_file_location(module_name, str(module_path_obj))

                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)

                        # CRITICAL: Register in sys.modules BEFORE execution
                        # This ensures decorators can find the module
                        sys.modules[module_name] = module

                        if execute:
                            # Execute module (triggers decorator registration)
                            spec.loader.exec_module(module)
                            logger.debug(
                                f"Loaded and executed module: {module_name} from {module_path_obj}"
                            )
                        else:
                            logger.debug(
                                f"Loaded module (not executed): {module_name} from {module_path_obj}"
                            )
                    else:
                        logger.warning(
                            f"Could not create spec for {module_name} from {module_path_obj}"
                        )

            except Exception as e:
                logger.warning(f"Failed to load module {module_name} from path: {e}")
                module = None

        # Fallback to standard import
        if module is None and fallback_import:
            try:
                module = importlib.import_module(module_name)
                logger.debug(f"Loaded module via standard import: {module_name}")
            except ImportError as e:
                logger.warning(f"Could not import module {module_name}: {e}")
                module = None

        # Cache the result (even if None to avoid repeated failures)
        if cache:
            _MODULE_CACHE[cache_key] = module

        return module


def clear_module_cache() -> None:
    """Clear the module cache (testing only).

    Note:
        This does NOT modify sys.modules itself.
        Only clears the internal cache tracking what was loaded.
    """
    with _LOCK:
        _MODULE_CACHE.clear()
        logger.debug("Cleared module cache")


# ==============================================================================
# High-Level API: UDF Discovery
# ==============================================================================


def discover_and_load_udfs(
    user_code_path: Union[str, Path],
    *,
    skip_private: bool = True,
    skip_test: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """Discover and load UDFs from Python files in a directory (non-recursive).

    Args:
        user_code_path: Root directory containing Python files
        skip_private: If True, skip files/dirs starting with underscore
        skip_test: If True, skip test files (test_*.py, *_test.py)

    Returns:
        Dict mapping module names to loaded module info:
        {
            "module_name": {
                "module": <module object>,
                "path": Path("/path/to/module.py")
            },
            ...
        }

    Example:
        >>> registry = discover_and_load_udfs("/path/to/user/code")
        >>> print(f"Loaded {len(registry)} modules")
    """
    user_code_path = Path(user_code_path).absolute()

    if not user_code_path.exists():
        logger.warning(f"User code path does not exist: {user_code_path}")
        return {}

    if not user_code_path.is_dir():
        logger.warning(f"User code path is not a directory: {user_code_path}")
        return {}

    # Ensure path is importable
    ensure_path_importable(user_code_path)

    registry: Dict[str, Dict[str, Any]] = {}

    # Find Python files (non-recursive)
    python_files = list(user_code_path.glob("*.py"))

    for py_file in python_files:
        # Skip filtered files
        if skip_private and py_file.name.startswith("_"):
            continue
        if skip_test and (py_file.name.startswith("test_") or py_file.name.endswith("_test.py")):
            continue

        # Load module
        module_name = py_file.stem
        module = load_module_from_path(
            module_name, py_file, execute=True, fallback_import=False, cache=True
        )

        if module:
            registry[module_name] = {"module": module, "path": py_file}

    logger.info(f"Discovered and loaded {len(registry)} modules from {user_code_path}")
    return registry


def discover_and_load_udfs_recursive(
    user_code_path: Union[str, Path],
    *,
    skip_private: bool = True,
    skip_test: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """Discover and load UDFs from Python files recursively in a directory tree.

    Args:
        user_code_path: Root directory containing Python files
        skip_private: If True, skip files/dirs starting with underscore
        skip_test: If True, skip test files (test_*.py, *_test.py)

    Returns:
        Dict mapping module names to loaded module info:
        {
            "module_name": {
                "module": <module object>,
                "path": Path("/path/to/module.py")
            },
            ...
        }

    Example:
        >>> registry = discover_and_load_udfs_recursive("/path/to/user/code")
        >>> print(f"Loaded {len(registry)} modules")

    Note:
        This recursively searches all subdirectories for .py files.
        Use this for projects with nested package structures.
    """
    user_code_path = Path(user_code_path).absolute()

    if not user_code_path.exists():
        logger.warning(f"User code path does not exist: {user_code_path}")
        return {}

    if not user_code_path.is_dir():
        logger.warning(f"User code path is not a directory: {user_code_path}")
        return {}

    # Ensure path is importable
    ensure_path_importable(user_code_path)

    registry: Dict[str, Dict[str, Any]] = {}

    # Find Python files recursively
    python_files = list(user_code_path.rglob("*.py"))

    for py_file in python_files:
        # Construct module name from relative path first (needed for filtering)
        try:
            rel_path = py_file.relative_to(user_code_path)
        except ValueError:
            # File is not relative to user_code_path, skip it
            continue

        # Skip filtered files/directories (check only relative path parts)
        if skip_private:
            # Check if any part of the relative path starts with underscore
            if any(part.startswith("_") for part in rel_path.parts):
                continue

        if skip_test and (py_file.name.startswith("test_") or py_file.name.endswith("_test.py")):
            continue

        # Ensure parent directory is importable
        ensure_path_importable(py_file.parent)

        # Construct module name from relative path
        module_parts = list(rel_path.parts[:-1]) + [rel_path.stem]
        module_name = ".".join(module_parts)

        # Load module
        module = load_module_from_path(
            module_name, py_file, execute=True, fallback_import=False, cache=True
        )

        if module:
            registry[module_name] = {"module": module, "path": py_file}

    logger.info(f"Discovered and loaded {len(registry)} modules from {user_code_path} (recursive)")
    return registry
