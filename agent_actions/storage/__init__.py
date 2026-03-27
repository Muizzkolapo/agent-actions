"""Pluggable storage layer for workflow data persistence."""

from pathlib import Path

from agent_actions.storage.backend import StorageBackend
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

BACKENDS: dict[str, type[StorageBackend]] = {
    "sqlite": SQLiteBackend,
}


def get_storage_backend(
    workflow_path: str,
    workflow_name: str,
    backend_type: str = "sqlite",
) -> StorageBackend:
    """Create a storage backend instance.

    Raises:
        ValueError: If backend_type is not registered.
    """
    if backend_type not in BACKENDS:
        available = ", ".join(BACKENDS.keys())
        raise ValueError(
            f"Unknown storage backend: '{backend_type}'. Available backends: {available}"
        )

    backend_class = BACKENDS[backend_type]

    workflow_dir = Path(workflow_path)
    db_path = workflow_dir / "agent_io" / "target" / f"{workflow_name}.db"
    backend = backend_class.create(db_path=str(db_path), workflow_name=workflow_name)

    return backend


__all__ = [
    "StorageBackend",
    "SQLiteBackend",
    "BACKENDS",
    "get_storage_backend",
]
