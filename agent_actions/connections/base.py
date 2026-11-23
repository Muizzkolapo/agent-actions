"""The contract a database connection meets, and the values that cross it."""

from __future__ import annotations

import base64
import datetime
import decimal
import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigurationError

Row = dict[str, Any]

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class WriteMode(str, Enum):
    """What a write does with the rows a table already holds."""

    APPEND = "append"
    REPLACE = "replace"
    MERGE = "merge"


class ColumnType(str, Enum):
    """What a column holds, for the table a write creates."""

    TEXT = "text"
    INTEGER = "integer"
    REAL = "real"
    BOOLEAN = "boolean"


class Connector(ABC):
    """One open connection to a database a workflow reads rows from and writes rows to."""

    @classmethod
    @abstractmethod
    def from_settings(cls, name: str, settings: dict[str, Any], project_root: Path) -> Connector:
        """Build from the entry the project's ``connections:`` block calls *name*."""

    @abstractmethod
    def check(self) -> None:
        """Raise ``ConfigurationError`` unless the database answers."""

    @abstractmethod
    def read(self, query: str) -> Iterator[Row]:
        """The rows *query* selects, one at a time, as the database's own values."""

    @abstractmethod
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
        """Write *rows* to *table* in one transaction and return how many were written.

        The table is created when it does not exist and there are rows to write,
        each column of the type *types* gives it.
        ``MERGE`` replaces the rows sharing a *key* with an incoming row, so
        writing the same rows twice leaves the table as writing them once did;
        it removes no other row, and refuses a row whose key is null.
        """

    @abstractmethod
    def close(self) -> None:
        """Release the connection."""

    def __enter__(self) -> Connector:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def quoted_identifier(name: str, quote: str = '"') -> str:
    """*name* wrapped in *quote* for SQL, each dotted part on its own.

    A table or column name is written into the statement, never bound, so only
    plain identifiers are let through. An empty *quote* leaves the name bare,
    for a database that folds the case of an unquoted name.
    """
    parts = name.split(".")
    if not all(_IDENTIFIER.fullmatch(part) for part in parts):
        raise ConfigurationError(
            f"'{name}' is not a table or column name: use letters, digits and "
            "underscores, with a dot between a schema and a table",
            context={"identifier": name},
        )
    return ".".join(f"{quote}{part}{quote}" for part in parts)


def json_safe(value: Any) -> Any:
    """*value* as JSON holds it, the same way on every read.

    A record's identity is a hash of its content, so a timestamp or a decimal
    has to come out as the same text each time the row is read.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, dict):
        return {str(name): json_safe(item) for name, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    raise ConfigurationError(
        f"A database value of type {type(value).__name__} has no JSON form; "
        "cast the column in the query",
        context={"type": type(value).__name__},
    )
