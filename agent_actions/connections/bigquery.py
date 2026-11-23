"""A connection to a Google BigQuery project."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_actions.connections.base import ColumnType
from agent_actions.connections.dbapi import DbApiConnector, Dialect
from agent_actions.connections.settings import read_settings


class BigquerySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    # The dataset of a table named without one.
    dataset: str | None = None
    location: str | None = None
    # A service-account key file; without one, the environment's own credentials.
    keyfile: str | None = None


class BigqueryConnector(DbApiConnector):
    """Reads and writes BigQuery through its client library.

    Rows are added by a load job, not by INSERT statements. A write is not one
    transaction: one that stops partway is put right by writing again (an
    append excepted).
    """

    kind = "bigquery"

    dialect = Dialect(
        quote="`",
        types={
            ColumnType.TEXT: "STRING",
            ColumnType.INTEGER: "INT64",
            ColumnType.REAL: "FLOAT64",
            ColumnType.BOOLEAN: "BOOL",
        },
        untyped="STRING",
    )

    def __init__(self, settings: BigquerySettings, project_root: Path) -> None:
        super().__init__()
        self._settings = settings
        self._project_root = project_root
        self._client: Any = None

    @classmethod
    def from_settings(
        cls, name: str, settings: dict[str, Any], project_root: Path
    ) -> BigqueryConnector:
        return cls(read_settings(name, settings, BigquerySettings), project_root)

    def _connect(self) -> Any:
        from google.cloud import bigquery
        from google.cloud.bigquery import dbapi

        settings = self._settings
        options: dict[str, Any] = {"project": settings.project, "location": settings.location}
        if settings.dataset:
            options["default_query_job_config"] = bigquery.QueryJobConfig(
                default_dataset=f"{settings.project}.{settings.dataset}"
            )
        if settings.keyfile:
            self._client = bigquery.Client.from_service_account_json(
                str(self._project_root / settings.keyfile), **options
            )
        else:
            self._client = bigquery.Client(**options)
        return dbapi.connect(self._client)

    def _insert(self, cursor: Any, table: str, columns: Sequence[str], rows: list[Any]) -> None:
        records = [dict(zip(columns, row, strict=True)) for row in rows]
        self._client.load_table_from_json(records, self._table_id(table)).result()

    def _table_id(self, table: str) -> str:
        """*table* as a load job names it: project, dataset and table."""
        self.dialect.identifier(table)
        parts = table.split(".")
        if len(parts) == 1 and self._settings.dataset:
            parts = [self._settings.dataset, *parts]
        if len(parts) == 2:
            parts = [self._settings.project, *parts]
        return ".".join(parts)
