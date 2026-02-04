"""
Extensible storage backend module.

This module provides a pluggable storage layer for workflow data persistence.
The default backend is SQLite, but the architecture supports future backends
like S3, DuckDB, or other storage systems.

Usage:
    from agent_actions.storage import get_storage_backend

    # Get a storage backend for a workflow
    backend = get_storage_backend(
        workflow_path="/path/to/workflow",
        workflow_name="my_workflow",
        backend_type="sqlite"  # default
    )

    # Use the backend
    backend.initialize()
    backend.write_target("node_1", "batch_001.json", data)
    records = backend.read_source("batch_001.json")
"""

from pathlib import Path
from typing import Dict, Type

from agent_actions.storage.backend import StorageBackend
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

# Registry of available backends
BACKENDS: Dict[str, Type[StorageBackend]] = {
    "sqlite": SQLiteBackend,
}


def get_storage_backend(
    workflow_path: str,
    workflow_name: str,
    backend_type: str = "sqlite",
) -> StorageBackend:
    """
    Factory function to create a storage backend instance.

    Args:
        workflow_path: Path to the workflow directory
        workflow_name: Name of the workflow (used for DB filename)
        backend_type: Type of backend to use (default: "sqlite")

    Returns:
        Initialized StorageBackend instance

    Raises:
        ValueError: If backend_type is not registered

    Example:
        >>> backend = get_storage_backend(
        ...     "/workflows/my_pipeline",
        ...     "my_pipeline",
        ...     backend_type="sqlite"
        ... )
        >>> backend.initialize()
    """
    if backend_type not in BACKENDS:
        available = ", ".join(BACKENDS.keys())
        raise ValueError(
            f"Unknown storage backend: '{backend_type}'. Available backends: {available}"
        )

    backend_class = BACKENDS[backend_type]

    # Build backend-specific configuration
    if backend_type == "sqlite":
        # SQLite: {workflow}/agent_io/target/{workflow_name}.db
        workflow_dir = Path(workflow_path)
        db_path = workflow_dir / "agent_io" / "target" / f"{workflow_name}.db"
        backend = backend_class(str(db_path), workflow_name)
    else:
        # Future backends may have different initialization
        # This is where we'd add S3, DuckDB, etc. configuration
        raise NotImplementedError(f"Backend '{backend_type}' initialization not implemented")

    return backend


def register_backend(name: str, backend_class: Type[StorageBackend]) -> None:
    """
    Register a custom storage backend.

    Args:
        name: Name to register the backend under
        backend_class: Class implementing StorageBackend

    Example:
        >>> class MyCustomBackend(StorageBackend):
        ...     # implementation
        ...     pass
        >>> register_backend("custom", MyCustomBackend)
    """
    BACKENDS[name] = backend_class


__all__ = [
    "StorageBackend",
    "SQLiteBackend",
    "BACKENDS",
    "get_storage_backend",
    "register_backend",
]
