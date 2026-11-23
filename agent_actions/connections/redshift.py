"""A connection to an Amazon Redshift cluster or workgroup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_actions.connections.base import ColumnType
from agent_actions.connections.dbapi import DbApiConnector, Dialect
from agent_actions.connections.settings import CREDENTIAL, read_settings


class RedshiftSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 5439
    database: str
    user: str | None = None
    password: str | None = Field(default=None, json_schema_extra=CREDENTIAL)
    # With iam, the driver signs in with the AWS credentials of the environment.
    iam: bool = False
    cluster_identifier: str | None = None
    region: str | None = None
    db_user: str | None = None
    sslmode: str | None = None


class RedshiftConnector(DbApiConnector):
    """Reads and writes Redshift through redshift_connector. A write is one transaction."""

    kind = "redshift"

    dialect = Dialect(
        types={
            ColumnType.TEXT: "VARCHAR(65535)",
            ColumnType.INTEGER: "BIGINT",
            ColumnType.REAL: "DOUBLE PRECISION",
            ColumnType.BOOLEAN: "BOOLEAN",
        },
        untyped="VARCHAR(65535)",
    )

    def __init__(self, settings: RedshiftSettings) -> None:
        super().__init__()
        self._settings = settings

    @classmethod
    def from_settings(
        cls, name: str, settings: dict[str, Any], project_root: Path
    ) -> RedshiftConnector:
        return cls(read_settings(name, settings, RedshiftSettings))

    def _connect(self) -> Any:
        import redshift_connector

        return redshift_connector.connect(**self._settings.model_dump(exclude_none=True))
