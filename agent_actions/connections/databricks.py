"""A connection to a Databricks SQL warehouse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_actions.connections.base import ColumnType
from agent_actions.connections.dbapi import DbApiConnector, Dialect
from agent_actions.connections.settings import CREDENTIAL, read_settings


class DatabricksSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_hostname: str
    http_path: str
    access_token: str = Field(json_schema_extra=CREDENTIAL)
    catalog: str | None = None
    # ``schema`` is a pydantic name, so the setting is read through an alias.
    schema_: str | None = Field(default=None, alias="schema")


class DatabricksConnector(DbApiConnector):
    """Reads and writes Databricks through its SQL connector.

    Each statement commits by itself: a write is not one transaction, and one
    that stops partway is put right by writing again (an append excepted).
    """

    kind = "databricks"

    dialect = Dialect(
        param_style="named",
        quote="`",
        types={
            ColumnType.TEXT: "STRING",
            ColumnType.INTEGER: "BIGINT",
            ColumnType.REAL: "DOUBLE",
            ColumnType.BOOLEAN: "BOOLEAN",
        },
        untyped="STRING",
        text_cast="STRING",
        add_column="ALTER TABLE {table} ADD COLUMNS ({column})",
        max_params=250,
    )

    def __init__(self, settings: DatabricksSettings) -> None:
        super().__init__()
        self._settings = settings

    @classmethod
    def from_settings(
        cls, name: str, settings: dict[str, Any], project_root: Path
    ) -> DatabricksConnector:
        return cls(read_settings(name, settings, DatabricksSettings))

    def _connect(self) -> Any:
        from databricks import sql

        options = self._settings.model_dump(exclude_none=True, by_alias=True)
        return sql.connect(**options)

    def _commit(self, connection: Any) -> None:
        """Nothing to commit: the connection commits each statement."""
