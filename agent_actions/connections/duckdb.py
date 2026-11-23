"""A connection to a DuckDB database file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_actions.connections.base import ColumnType
from agent_actions.connections.dbapi import DbApiConnector, Dialect
from agent_actions.connections.settings import read_settings


class DuckdbSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class DuckdbConnector(DbApiConnector):
    """Reads and writes one DuckDB file. A write is one transaction, table creation included."""

    kind = "duckdb"

    dialect = Dialect(
        param_style="qmark",
        types={
            ColumnType.TEXT: "VARCHAR",
            ColumnType.INTEGER: "BIGINT",
            ColumnType.REAL: "DOUBLE",
            ColumnType.BOOLEAN: "BOOLEAN",
        },
        untyped="VARCHAR",
    )

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    @classmethod
    def from_settings(
        cls, name: str, settings: dict[str, Any], project_root: Path
    ) -> DuckdbConnector:
        """``path`` is relative to the project."""
        return cls(project_root / read_settings(name, settings, DuckdbSettings).path)

    def _connect(self) -> Any:
        import duckdb

        return duckdb.connect(str(self._path))

    def _begin(self, connection: Any) -> None:
        connection.begin()

    def _cursor(self, connection: Any) -> Any:
        return _OwnTransaction(connection)


class _OwnTransaction:
    """The connection, used as its own cursor.

    DuckDB's ``cursor()`` is another connection, outside the transaction this
    one began: rows written through it would stay after a rollback.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def close(self) -> None:
        """Nothing to close: the connection outlives each statement."""
