"""A connection to a PostgreSQL database."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_actions.connections.dbapi import DbApiConnector, Dialect
from agent_actions.connections.settings import CREDENTIAL, read_settings


class PostgresSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 5432
    dbname: str
    user: str
    password: str | None = Field(default=None, json_schema_extra=CREDENTIAL)
    sslmode: str | None = None
    connect_timeout: int = 10


class PostgresConnector(DbApiConnector):
    """Reads and writes PostgreSQL through psycopg. A write is one transaction, DDL included."""

    # A quoted name keeps its case, so "Summary" and "summary" are two columns.
    dialect = Dialect(case_sensitive_names=True)

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

        options = self._settings.model_dump(exclude_none=True)
        if self.read_only:
            options["options"] = "-c default_transaction_read_only=on"
        # Text in a SQL_ASCII database comes back as bytes unless the client asks for utf8.
        return psycopg.connect(client_encoding="utf8", **options)

    def _read_cursor(self, connection: Any) -> Any:
        # A named cursor is held by the server, so a large result is not read into memory.
        return connection.cursor(name="agac_read")
