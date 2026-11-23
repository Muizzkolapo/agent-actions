"""A connection to a MySQL or MariaDB database."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_actions.connections.base import ColumnType
from agent_actions.connections.dbapi import DbApiConnector, Dialect
from agent_actions.connections.settings import read_settings


class MysqlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "localhost"
    port: int = 3306
    database: str
    user: str
    password: str | None = None
    unix_socket: str | None = None
    connect_timeout: int = 10


class MysqlConnector(DbApiConnector):
    """Reads and writes MySQL through PyMySQL.

    Rows are written in one transaction, but MySQL commits a CREATE TABLE at
    once: a first write that fails leaves the new table behind, empty.
    """

    kind = "mysql"

    dialect = Dialect(
        quote="`",
        types={
            ColumnType.TEXT: "TEXT",
            ColumnType.INTEGER: "BIGINT",
            ColumnType.REAL: "DOUBLE",
            ColumnType.BOOLEAN: "BOOLEAN",
        },
    )

    def __init__(self, settings: MysqlSettings) -> None:
        super().__init__()
        self._settings = settings

    @classmethod
    def from_settings(
        cls, name: str, settings: dict[str, Any], project_root: Path
    ) -> MysqlConnector:
        return cls(read_settings(name, settings, MysqlSettings))

    def _connect(self) -> Any:
        import pymysql

        options = self._settings.model_dump(exclude_none=True)
        return pymysql.connect(charset="utf8mb4", **options)

    def _read_cursor(self, connection: Any) -> Any:
        import pymysql.cursors

        # Unbuffered, so a large result is not read into memory.
        return connection.cursor(pymysql.cursors.SSCursor)
