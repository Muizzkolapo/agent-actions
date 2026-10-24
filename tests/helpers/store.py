"""Read a workflow store with SQL, getting its compressed payload columns back as text."""

from pathlib import Path
from typing import Any

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def stored_rows(db: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    """Run *sql* against the store at *db*, read-only.

    A value the backend stored compressed (``target_data.data``, ``source_data.data``,
    ``checkpoint_output.record_data``, ``record_disposition.input_snapshot``) comes back
    as the text that was written, so a test parses it as it always did.
    """
    backend = SQLiteBackend.create_readonly(db)
    try:
        rows = backend.connection.execute(sql, params).fetchall()
        return [
            tuple(backend.payload_text(value, table="store", where=sql) for value in row)
            for row in rows
        ]
    finally:
        backend.close()
