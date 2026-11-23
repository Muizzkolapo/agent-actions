"""A connection to a PostgreSQL database."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_actions.connections.dbapi import DbApiConnector
from agent_actions.connections.settings import read_settings


class PostgresSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 5432
    dbname: str
    user: str
    password: str | None = Field(default=None, json_schema_extra={"secret": True})
    sslmode: str | None = None
    connect_timeout: int = 10


class PostgresConnector(DbApiConnector):
    """Reads and writes PostgreSQL through psycopg. A write is one transaction, DDL included."""

    kind = "postgres"

    def __init__(self, settings: PostgresSettings) -> None:
        super().__init__()
        self._settings = settings

    @classmethod
    def from_settings(
        cls, name: str, settings: dict[str, Any], project_root: Path
    ) -> PostgresConnector:
        return cls(read_settings(name, settings, PostgresSettings))

    def _connect(self) -> Any:
        import psycopg

        return psycopg.connect(**self._settings.model_dump(exclude_none=True))

    def _read_cursor(self, connection: Any) -> Any:
        # A named cursor is held by the server, so a large result is not read into memory.
        return connection.cursor(name="agac_read")
