"""A connection to a Snowflake account."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_actions.connections.base import ColumnType
from agent_actions.connections.dbapi import DbApiConnector, Dialect
from agent_actions.connections.settings import CREDENTIAL, read_settings


class SnowflakeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str
    user: str
    password: str | None = Field(default=None, json_schema_extra=CREDENTIAL)
    private_key_file: str | None = None
    private_key_file_pwd: str | None = Field(default=None, json_schema_extra=CREDENTIAL)
    authenticator: str | None = None
    warehouse: str | None = None
    database: str | None = None
    # ``schema`` is a pydantic name, so the setting is read through an alias.
    schema_: str | None = Field(default=None, alias="schema")
    role: str | None = None


class SnowflakeConnector(DbApiConnector):
    """Reads and writes Snowflake through its Python connector.

    Names are quoted upper-cased, the name Snowflake gives an unquoted one, so
    a table made by hand is found and a reserved word is still a name; a result
    column in upper case is read back in lower case. Rows are written in one
    transaction, but Snowflake commits a CREATE TABLE at once: a first write
    that fails leaves the new table behind.
    """

    kind = "snowflake"
    driver = "snowflake.connector"

    dialect = Dialect(
        fold_upper=True,
        types={
            ColumnType.TEXT: "VARCHAR",
            ColumnType.INTEGER: "NUMBER(38, 0)",
            ColumnType.REAL: "FLOAT",
            ColumnType.BOOLEAN: "BOOLEAN",
        },
        untyped="VARCHAR",
        text_cast="VARCHAR",
    )

    def __init__(self, settings: SnowflakeSettings) -> None:
        super().__init__()
        self._settings = settings

    @classmethod
    def from_settings(
        cls, name: str, settings: dict[str, Any], project_root: Path
    ) -> SnowflakeConnector:
        return cls(read_settings(name, settings, SnowflakeSettings))

    def _connect(self) -> Any:
        import snowflake.connector

        options = self._settings.model_dump(exclude_none=True, by_alias=True)
        return snowflake.connector.connect(autocommit=False, **options)

    def _column_name(self, name: str) -> str:
        return name.lower() if name.isupper() else name
