"""Thread-safe, cached module loading and UDF discovery for dynamic imports."""

import importlib
import importlib.util
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from agent_actions.logging import fire_event
from agent_actions.logging.events.cache_events import (
    CacheHitEvent,
    CacheInvalidationEvent,
    CacheMissEvent,
)

logger = logging.getLogger(__name__)

__all__ = [
    "load_module_from_path",
    "load_module_from_directory",
    "clear_module_cache",
    "discover_and_load_udfs",
    "discover_and_load_udfs_recursive",
]

_LOCK = threading.RLock()
_MODULE_CACHE: dict[str, Any] = {}


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
                initial_path = Path(module_path)
                module_path_obj: Path | None = initial_path

                if initial_path.is_dir():
                    init_file = initial_path / "__init__.py"
                    module_file = initial_path / f"{module_name}.py"

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
                        sys.modules[f"agent_actions._udfs.{module_name}"] = module

                        if execute:
                            try:
                                spec.loader.exec_module(module)
                            except Exception as e:
                                # Module file found but its code is broken.
                                # Clean up and block fallback so a different
                                # same-named package doesn't silently replace it.
                                sys.modules.pop(f"agent_actions._udfs.{module_name}", None)
                                logger.warning(
                                    "Failed to execute module %s from %s: %s",
                                    module_name,
                                    module_path_obj,
                                    e,
                                    exc_info=True,
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
                sys.modules.pop(f"agent_actions._udfs.{module_name}", None)
                logger.warning(
                    "Failed to load module %s from path: %s", module_name, e, exc_info=True
                )
                module = None

        # Skip fallback when path-based load raised to avoid silently replacing
        if module is None and fallback_import and not path_load_failed:
            try:
                module = importlib.import_module(module_name)
                logger.debug("Loaded module via standard import: %s", module_name)
            except ImportError as e:
                logger.warning("Could not import module %s: %s", module_name, e, exc_info=True)
                module = None

        if cache and (module is not None or cache_failures):
            _MODULE_CACHE[cache_key] = module

        return module


def _resolve_module_file(module_name: str, search_dir: str | Path) -> Path | None:
    """Resolve a dotted module name to a .py file within search_dir."""
    if not module_name:
        return None
    search_dir = Path(search_dir)
    relative = Path(*module_name.split("."))

    candidate = search_dir / relative.with_suffix(".py")
    if candidate.is_file():
        return candidate

    candidate = search_dir / relative / "__init__.py"
    if candidate.is_file():
        return candidate

    return None


def load_module_from_directory(
    module_name: str,
    search_dir: str | Path,
    *,
    execute: bool = True,
    cache: bool = True,
    fallback_import: bool = True,
) -> Any | None:
    """Load a module by name from a directory without mutating sys.path.

    Resolve the module name to a file path within search_dir via
    ``_resolve_module_file``, then delegate to ``load_module_from_path``.
    Fall back to standard import if the file is not found and
    *fallback_import* is True (the default).
    """
    module_file = _resolve_module_file(module_name, search_dir)
    if module_file:
        return load_module_from_path(
            module_name,
            module_file,
            execute=execute,
            fallback_import=False,
            cache=cache,
        )
    if fallback_import:
        logger.debug(
            "Module %s not found in %s, falling back to standard import", module_name, search_dir
        )
    return load_module_from_path(
        module_name,
        None,
        execute=execute,
        fallback_import=fallback_import,
        cache=cache,
    )


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
