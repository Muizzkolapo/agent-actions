"""A connection to a SQLite database file."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from itertools import chain
from pathlib import Path
from typing import Any

from agent_actions.connections.base import (
    ColumnType,
    Connector,
    Row,
    WriteMode,
    quoted_identifier,
)
from agent_actions.errors import ConfigurationError

_INSERT_BATCH = 500


class SqliteConnector(Connector):
    """Reads and writes one SQLite file; the reference connector, and the one tests run on."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: sqlite3.Connection | None = None

    @classmethod
    def from_settings(cls, settings: dict[str, Any], project_root: Path) -> SqliteConnector:
        """Build from a ``connections:`` entry; ``path`` is relative to the project."""
        path = settings.get("path")
        if not isinstance(path, str) or not path:
            raise ConfigurationError(
                "A sqlite connection needs a 'path' to the database file",
                context={"settings": sorted(settings)},
            )
        return cls(project_root / path)

    def _open(self) -> sqlite3.Connection:
        if self._connection is None:
            try:
                # Autocommit, so write() opens its own transaction and the
                # CREATE TABLE is rolled back with the rows.
                self._connection = sqlite3.connect(self._path, isolation_level=None)
            except sqlite3.Error as error:
                raise ConfigurationError(
                    f"Cannot open the SQLite database at {self._path}: {error}",
                    context={"path": str(self._path)},
                    cause=error,
                ) from error
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def check(self) -> None:
        self._open().execute("SELECT 1").fetchone()

    def read(self, query: str) -> Iterator[Row]:
        try:
            cursor = self._open().execute(query)
        except sqlite3.Error as error:
            raise ConfigurationError(
                f"The query failed: {error}", context={"query": query}, cause=error
            ) from error
        for row in cursor:
            yield dict(row)

    def write(
        self,
        table: str,
        columns: Sequence[str],
        rows: Iterable[Sequence[Any]],
        *,
        mode: WriteMode,
        key: Sequence[str] = (),
        types: Mapping[str, ColumnType] | None = None,
    ) -> int:
        if mode is WriteMode.MERGE and not key:
            raise ConfigurationError(
                "A merge needs the key columns that identify a row", context={"table": table}
            )
        target = quoted_identifier(table)
        names = [quoted_identifier(column) for column in columns]
        kinds = types or {}
        # A column given no type is declared with none, so it holds a value as written.
        declared = [
            f"{name} {kinds[column].value.upper()}" if column in kinds else name
            for name, column in zip(names, columns, strict=True)
        ]
        key_positions = [columns.index(column) for column in key]
        key_match = " AND ".join(f"{quoted_identifier(column)} IS ?" for column in key)
        # A name cannot be bound as a value is; quoted_identifier lets only plain names by.
        marks = ", ".join("?" for _ in names)
        insert = f"INSERT INTO {target} ({', '.join(names)}) VALUES ({marks})"  # nosec B608
        delete_all = f"DELETE FROM {target}"  # nosec B608
        delete_keyed = f"DELETE FROM {target} WHERE {key_match}"  # nosec B608
        connection = self._open()
        written = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            batches = _batches(rows, _INSERT_BATCH)
            first = next(batches, None)
            if first is None and not self._held_columns(connection, table):
                connection.execute("ROLLBACK")
                return 0
            connection.execute(f"CREATE TABLE IF NOT EXISTS {target} ({', '.join(declared)})")
            if first is not None:
                self._refuse_missing_columns(connection, table, columns)
            if mode is WriteMode.REPLACE:
                connection.execute(delete_all)
            for batch in [] if first is None else chain([first], batches):
                if mode is WriteMode.MERGE:
                    connection.executemany(
                        delete_keyed,
                        [[row[position] for position in key_positions] for row in batch],
                    )
                connection.executemany(insert, batch)
                written += len(batch)
            connection.execute("COMMIT")
        except ConfigurationError:
            connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise ConfigurationError(
                f"Writing to {table} failed and nothing was written: {error}",
                context={"table": table, "mode": mode.value},
                cause=error,
            ) from error
        return written

    @staticmethod
    def _held_columns(connection: sqlite3.Connection, table: str) -> set[str]:
        """The columns *table* has; none when there is no such table."""
        schema, _, bare = table.rpartition(".")
        found = connection.execute(
            "SELECT name FROM pragma_table_info(?, ?)", (bare, schema or "main")
        )
        return {row["name"] for row in found}

    def _refuse_missing_columns(
        self, connection: sqlite3.Connection, table: str, columns: Sequence[str]
    ) -> None:
        held = self._held_columns(connection, table)
        missing = [column for column in columns if column not in held]
        if missing:
            raise ConfigurationError(
                f"Table {table} has no column {', '.join(missing)}; add it, or write "
                "to a new table",
                context={"table": table, "missing": missing},
            )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _batches(rows: Iterable[Sequence[Any]], size: int) -> Iterator[list[Sequence[Any]]]:
    batch: list[Sequence[Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
