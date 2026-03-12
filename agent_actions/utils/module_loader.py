"""Thread-safe, cached module loading and UDF discovery for dynamic imports."""

import importlib
import importlib.util
import logging
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agent_actions.logging import fire_event
from agent_actions.logging.events.types import CacheHitEvent, CacheInvalidationEvent, CacheMissEvent

logger = logging.getLogger(__name__)

# Public API
__all__ = [
    # Low-level API
    "ensure_path_importable",
    "ensure_paths_importable",
    "importable_path",
    "clear_path_cache",
    # Mid-level API
    "load_module_from_path",
    "clear_module_cache",
    # High-level API
    "discover_and_load_udfs",
    "discover_and_load_udfs_recursive",
]

# Thread-safe caches
_LOCK = threading.RLock()
_PATH_CACHE: set[str] = set()
_MODULE_CACHE: dict[str, Any] = {}


# ==============================================================================
# Low-Level API: Path Management
# ==============================================================================


def ensure_path_importable(path: str | Path, *, recursive: bool = False) -> bool:
    """Ensure a path is in sys.path for imports (thread-safe, cached).

    Args:
        path: Directory path to add to sys.path.
        recursive: If True, also add all subdirectories (for nested packages).
            The lock is NOT held during traversal.

    Returns:
        True if path was added to cache, False if already cached.

    Note:
        Uses absolute() instead of resolve() to preserve symlinks.
    """
    path_str = str(Path(path).absolute())

    with _LOCK:
        if path_str in _PATH_CACHE:
            fire_event(CacheHitEvent(cache_type="module_path", key=path_str))
            return False

        fire_event(
            CacheMissEvent(cache_type="module_path", key=path_str, reason="path not in cache")
        )

        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            logger.debug("Added to sys.path: %s", path_str)

        _PATH_CACHE.add(path_str)

    if recursive:
        path_obj = Path(path)
        if path_obj.is_dir():
            for subdir in path_obj.rglob("*"):
                if subdir.is_dir() and not subdir.name.startswith("_"):
                    ensure_path_importable(subdir, recursive=False)

    return True


def ensure_paths_importable(paths: list[str | Path], *, recursive: bool = False) -> int:
    """Ensure multiple paths are in sys.path, returning count of newly added paths."""
    added_count = 0
    for path in paths:
        if ensure_path_importable(path, recursive=recursive):
            added_count += 1
    return added_count


@contextmanager
def importable_path(path: str | Path, *, recursive: bool = False):
    """Context manager for temporary sys.path modification (testing only).

    Does NOT use the cache, ensuring test isolation.
    In production, prefer ensure_path_importable().

    Yields:
        The resolved path string.
    """
    path_str = str(Path(path).absolute())
    paths_to_remove = []

    try:
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            paths_to_remove.append(path_str)

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
        for p in paths_to_remove:
            try:
                sys.path.remove(p)
            except ValueError:
                pass  # Already removed


def clear_path_cache() -> None:
    """Clear the path cache (testing only). Does not modify sys.path itself."""
    with _LOCK:
        entries_removed = len(_PATH_CACHE)
        _PATH_CACHE.clear()
        logger.debug("Cleared path cache")

        fire_event(
            CacheInvalidationEvent(
                cache_type="module_path", entries_removed=entries_removed, reason="manual clear"
            )
        )


# ==============================================================================
# Mid-Level API: Module Loading
# ==============================================================================


def load_module_from_path(
    module_name: str,
    module_path: str | Path | None = None,
    *,
    execute: bool = True,
    fallback_import: bool = True,
    cache: bool = True,
    cache_failures: bool = False,
) -> Any | None:
    """Load a module from a file path or standard import (thread-safe, cached).

    Args:
        module_name: Name of the module.
        module_path: Optional path to .py file or directory containing module.
        execute: If True, execute the module (triggers decorators).
        fallback_import: If True, try standard import if path load fails.
        cache: If True, return cached module on subsequent calls.
        cache_failures: If True, cache None results to prevent repeated failures.

    Returns:
        The loaded module object, or None if loading failed.

    Note:
        Modules are registered in sys.modules BEFORE execution so that
        decorator side effects (e.g., @udf_tool) work correctly.
    """
    cache_key = f"{module_name}:{module_path}" if module_path else module_name

    with _LOCK:
        if cache and cache_key in _MODULE_CACHE:
            logger.debug("Returning cached module: %s", module_name)
            fire_event(CacheHitEvent(cache_type="module", key=module_name))
            return _MODULE_CACHE[cache_key]

        fire_event(
            CacheMissEvent(cache_type="module", key=module_name, reason="module not in cache")
        )

        module = None
        path_load_failed = False

        if module_path:
            try:
                module_path_obj = Path(module_path)

                if module_path_obj.is_dir():
                    init_file = module_path_obj / "__init__.py"
                    module_file = module_path_obj / f"{module_name}.py"

                    if init_file.exists():
                        module_path_obj = init_file
                    elif module_file.exists():
                        module_path_obj = module_file
                    else:
                        logger.warning("No valid module file found in %s", module_path)
                        module_path_obj = None

                if module_path_obj and module_path_obj.is_file():
                    spec = importlib.util.spec_from_file_location(module_name, str(module_path_obj))

                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)

                        # CRITICAL: Register in sys.modules BEFORE execution
                        # This ensures decorators can find the module
                        sys.modules[module_name] = module

                        if execute:
                            try:
                                spec.loader.exec_module(module)
                            except Exception as e:
                                # Module file found but its code is broken.
                                # Clean up and block fallback so a different
                                # same-named package doesn't silently replace it.
                                sys.modules.pop(module_name, None)
                                logger.warning(
                                    "Failed to execute module %s from %s: %s",
                                    module_name,
                                    module_path_obj,
                                    e,
                                )
                                module = None
                                path_load_failed = True
                            else:
                                logger.debug(
                                    "Loaded and executed module: %s from %s",
                                    module_name,
                                    module_path_obj,
                                )
                        else:
                            logger.debug(
                                "Loaded module (not executed): %s from %s",
                                module_name,
                                module_path_obj,
                            )
                    else:
                        logger.warning(
                            "Could not create spec for %s from %s", module_name, module_path_obj
                        )

            except Exception as e:
                # Path resolution or spec creation failed — the file couldn't
                # be located.  Clean up but allow fallback_import to try a
                # normal import (the module may be importable via sys.path).
                sys.modules.pop(module_name, None)
                logger.warning("Failed to load module %s from path: %s", module_name, e)
                module = None

        # Skip fallback when path-based load raised to avoid silently replacing
        if module is None and fallback_import and not path_load_failed:
            try:
                module = importlib.import_module(module_name)
                logger.debug("Loaded module via standard import: %s", module_name)
            except ImportError as e:
                logger.warning("Could not import module %s: %s", module_name, e)
                module = None

        if cache and (module is not None or cache_failures):
            _MODULE_CACHE[cache_key] = module

        return module


def clear_module_cache() -> None:
    """Clear the module cache (testing only). Does not modify sys.modules itself."""
    with _LOCK:
        entries_removed = len(_MODULE_CACHE)
        _MODULE_CACHE.clear()
        logger.debug("Cleared module cache")

        fire_event(
            CacheInvalidationEvent(
                cache_type="module", entries_removed=entries_removed, reason="manual clear"
            )
        )


# ==============================================================================
# High-Level API: UDF Discovery
# ==============================================================================


def discover_and_load_udfs(
    user_code_path: str | Path,
    *,
    skip_private: bool = True,
    skip_test: bool = True,
) -> dict[str, dict[str, Any]]:
    """Discover and load UDFs from Python files in a directory (non-recursive).

    Args:
        user_code_path: Root directory containing Python files.
        skip_private: If True, skip files/dirs starting with underscore.
        skip_test: If True, skip test files (test_*.py, *_test.py).

    Returns:
        Dict mapping module names to ``{"module": <module>, "path": Path}``.
    """
    user_code_path = Path(user_code_path).absolute()

    if not user_code_path.exists():
        logger.warning("User code path does not exist: %s", user_code_path)
        return {}

    if not user_code_path.is_dir():
        logger.warning("User code path is not a directory: %s", user_code_path)
        return {}

    ensure_path_importable(user_code_path)

    registry: dict[str, dict[str, Any]] = {}

    python_files = list(user_code_path.glob("*.py"))

    for py_file in python_files:
        if skip_private and py_file.name.startswith("_"):
            continue
        if skip_test and (py_file.name.startswith("test_") or py_file.name.endswith("_test.py")):
            continue

        module_name = py_file.stem
        module = load_module_from_path(
            module_name, py_file, execute=True, fallback_import=False, cache=True
        )

        if module:
            registry[module_name] = {"module": module, "path": py_file}

    logger.info("Discovered and loaded %d modules from %s", len(registry), user_code_path)
    return registry


def discover_and_load_udfs_recursive(
    user_code_path: str | Path,
    *,
    skip_private: bool = True,
    skip_test: bool = True,
) -> dict[str, dict[str, Any]]:
    """Discover and load UDFs from Python files recursively in a directory tree.

    Args:
        user_code_path: Root directory containing Python files.
        skip_private: If True, skip files/dirs starting with underscore.
        skip_test: If True, skip test files (test_*.py, *_test.py).

    Returns:
        Dict mapping module names to ``{"module": <module>, "path": Path}``.
    """
    user_code_path = Path(user_code_path).absolute()

    if not user_code_path.exists():
        logger.warning("User code path does not exist: %s", user_code_path)
        return {}

    if not user_code_path.is_dir():
        logger.warning("User code path is not a directory: %s", user_code_path)
        return {}

    ensure_path_importable(user_code_path)

    registry: dict[str, dict[str, Any]] = {}

    python_files = list(user_code_path.rglob("*.py"))

    for py_file in python_files:
        try:
            rel_path = py_file.relative_to(user_code_path)
        except ValueError:
            continue

        if skip_private:
            if any(part.startswith("_") for part in rel_path.parts):
                continue

        if skip_test and (py_file.name.startswith("test_") or py_file.name.endswith("_test.py")):
            continue

        ensure_path_importable(py_file.parent)

        module_parts = list(rel_path.parts[:-1]) + [rel_path.stem]
        module_name = ".".join(module_parts)

        module = load_module_from_path(
            module_name, py_file, execute=True, fallback_import=False, cache=True
        )

        if module:
            registry[module_name] = {"module": module, "path": py_file}

    logger.info(
        "Discovered and loaded %d modules from %s (recursive)", len(registry), user_code_path
    )
    return registry
