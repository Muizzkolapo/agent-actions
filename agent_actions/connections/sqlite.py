"""A connection to a SQLite database file."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_actions.connections.base import ColumnType
from agent_actions.connections.dbapi import DbApiConnector, Dialect
from agent_actions.connections.settings import read_settings


class SqliteSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class SqliteConnector(DbApiConnector):
    """Reads and writes one SQLite file; on the standard library, so the one every test runs on."""

    kind = "sqlite"

    dialect = Dialect(
        param_style="qmark",
        types={
            ColumnType.TEXT: "TEXT",
            ColumnType.INTEGER: "INTEGER",
            ColumnType.REAL: "REAL",
            ColumnType.BOOLEAN: "BOOLEAN",
        },
        # A column with no type holds a value as written; TEXT would turn 1 into '1'.
        untyped=None,
        # The limit of a SQLite built before 3.32.
        max_params=999,
    )

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    @classmethod
    def from_settings(
        cls, name: str, settings: dict[str, Any], project_root: Path
    ) -> SqliteConnector:
        """``path`` is relative to the project."""
        return cls(project_root / read_settings(name, settings, SqliteSettings).path)

    def _connect(self) -> sqlite3.Connection:
        # Autocommit, so a write opens its own transaction and the CREATE TABLE
        # is rolled back with the rows.
        return sqlite3.connect(self._path, isolation_level=None)

    def _begin(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
