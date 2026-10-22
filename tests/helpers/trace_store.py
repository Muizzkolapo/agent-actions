"""Read a workflow store's prompt traces with SQL, getting the trace text back as written."""

from pathlib import Path
from typing import Any

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def store_path(project: Path) -> Path:
    (db,) = (Path(project) / "agent_workflow").glob("*/agent_io/store/*.db")
    return db


def trace_rows(project: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    """Run *sql* against the project's store; compressed trace text comes back as text."""
    backend = SQLiteBackend.create_readonly(store_path(project))
    try:
        rows = backend.connection.execute(sql, params).fetchall()
        return [tuple(backend.decompress_trace_text(value) for value in row) for row in rows]
    finally:
        backend.close()
