"""One connector over any PEP 249 driver; a database adds how to connect and its dialect."""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import chain
from typing import Any, Literal

from agent_actions.connections.base import (
    ColumnType,
    Connector,
    Row,
    WriteMode,
    quoted_identifier,
)
from agent_actions.errors import ConfigurationError

logger = logging.getLogger(__name__)

_READ_BATCH = 1000

# How each driver says a table does not exist, in lower case.
_MISSING_TABLE = (
    "no such table",  # sqlite
    "does not exist",  # postgres, redshift, duckdb, snowflake
    "doesn't exist",  # mysql
    "not found: table",  # bigquery
    "table_or_view_not_found",  # databricks
)
_WRITE_BATCH = 500

_STANDARD_TYPES: Mapping[ColumnType, str] = {
    ColumnType.TEXT: "TEXT",
    ColumnType.INTEGER: "BIGINT",
    ColumnType.REAL: "DOUBLE PRECISION",
    ColumnType.BOOLEAN: "BOOLEAN",
}


@dataclass(frozen=True)
class Dialect:
    """How one database spells what every database is asked for."""

    param_style: Literal["qmark", "format", "named"] = "format"
    quote: str = '"'
    # Quote each name upper-cased: the name a database that folds unquoted names
    # stores, still quoted, so a reserved word is a name and not a keyword.
    fold_upper: bool = False
    # The most values one statement binds; a batch is split to stay under it.
    max_params: int = 2000
    types: Mapping[ColumnType, str] = field(default_factory=lambda: _STANDARD_TYPES)
    # The type of a column given none; None declares the column with no type.
    untyped: str | None = "TEXT"

    def identifier(self, name: str) -> str:
        return quoted_identifier(name.upper() if self.fold_upper else name, self.quote)

    def markers(self, count: int) -> list[str]:
        """The *count* value markers of one statement, in order."""
        if self.param_style == "named":
            return [f":p{position}" for position in range(count)]
        return ["?" if self.param_style == "qmark" else "%s"] * count

    def bound(self, values: Sequence[Any]) -> Any:
        """*values* as the driver takes them for :meth:`markers`."""
        if self.param_style == "named":
            return {f"p{position}": value for position, value in enumerate(values)}
        return tuple(values)

    def column(self, name: str, kind: ColumnType | None) -> str:
        declared = self.untyped if kind is None else self.types[kind]
        return f"{self.identifier(name)} {declared}" if declared else self.identifier(name)


class DbApiConnector(Connector):
    """Reads and writes through a PEP 249 connection.

    A write is one transaction where the database has them. Where it has none
    (see a connector's own notes), a write that stops partway is put right by
    writing again: a replace or a merge written twice leaves what one leaves.
    """

    dialect = Dialect()
    # The connection type a project names, which is also the name of the driver's extra.
    kind = "database"

    def __init__(self) -> None:
        self._connection: Any = None

    @abstractmethod
    def _connect(self) -> Any:
        """Open the driver's connection; raise whatever the driver raises."""

    def _begin(self, connection: Any) -> None:
        """Start a transaction, for a driver that does not start one itself."""

    def _commit(self, connection: Any) -> None:
        connection.commit()

    def _cursor(self, connection: Any) -> Any:
        """A cursor whose statements run in the connection's own transaction."""
        return connection.cursor()

    def _read_cursor(self, connection: Any) -> Any:
        return self._cursor(connection)

    def _column_name(self, name: str) -> str:
        """The field a result column becomes."""
        return name

    def _insert(self, cursor: Any, table: str, columns: Sequence[str], rows: list[Any]) -> None:
        """Add *rows*, many to a statement; a database with a faster path overrides this.

        One INSERT a row is one round trip, and on a warehouse one job, a row.
        """
        dialect = self.dialect
        names = ", ".join(dialect.identifier(column) for column in columns)
        target = dialect.identifier(table)
        for chunk in _statement_chunks(rows, len(columns), dialect.max_params):
            markers = iter(dialect.markers(len(chunk) * len(columns)))
            values = ", ".join("(" + ", ".join(next(markers) for _ in columns) + ")" for _ in chunk)
            # Names are validated identifiers and every value is bound.
            statement = f"INSERT INTO {target} ({names}) VALUES {values}"  # nosec B608
            cursor.execute(statement, dialect.bound([value for row in chunk for value in row]))

    def _open(self) -> Any:
        if self._connection is None:
            try:
                self._connection = self._connect()
            except ConfigurationError:
                raise
            except ImportError as error:
                raise ConfigurationError(
                    f"A {self.kind} connection needs a driver that is not installed "
                    f"({error.name}). Install it with: pip install 'agent-actions[{self.kind}]'",
                    cause=error,
                ) from error
            except Exception as error:
                raise ConfigurationError(
                    f"Cannot connect to the {self.kind} database: {error}", cause=error
                ) from error
        return self._connection

    def check(self) -> None:
        for _ in self.read("SELECT 1 AS answered"):
            return

    def read(self, query: str) -> Iterator[Row]:
        connection = self._open()
        cursor = None
        try:
            cursor = self._read_cursor(connection)
            cursor.execute(query)
            if cursor.description is None:
                raise ConfigurationError(
                    "The query returned no rows to read: end it in a SELECT",
                    context={"query": query},
                )
            names = [self._column_name(column[0]) for column in cursor.description]
            repeated = sorted({name for name in names if names.count(name) > 1})
            if repeated:
                raise ConfigurationError(
                    f"The query returns {', '.join(repeated)} more than once; give each "
                    "column its own name with AS",
                    context={"query": query, "repeated": repeated},
                )
            while batch := cursor.fetchmany(_READ_BATCH):
                for values in batch:
                    yield dict(zip(names, values, strict=True))
        except ConfigurationError:
            raise
        except Exception as error:
            raise ConfigurationError(
                f"The query failed: {error}", context={"query": query}, cause=error
            ) from error
        finally:
            # Closed on every path: an unbuffered result left open blocks the next query.
            _close_quietly(cursor)
            self._rollback(connection)

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
        if mode is WriteMode.MERGE and not key:
            raise ConfigurationError(
                "A merge needs the key columns that identify a row", context={"table": table}
            )
        if mode is WriteMode.APPEND and key:
            rows = self._not_held(table, columns, rows, key)
        dialect = self.dialect
        target = dialect.identifier(table)
        key_positions = [columns.index(column) for column in key]
        connection = self._open()
        held = self._held_columns(connection, table)
        batches = _batches(rows, _WRITE_BATCH)
        first = next(batches, None)
        if first is None and held is None:
            return 0
        written = 0
        try:
            self._begin(connection)
            cursor = self._cursor(connection)
            if held is None:
                kinds = types or {}
                declared = ", ".join(dialect.column(name, kinds.get(name)) for name in columns)
                cursor.execute(f"CREATE TABLE IF NOT EXISTS {target} ({declared})")
            elif first is not None:
                _refuse_missing_columns(table, columns, held, exact=not dialect.fold_upper)
            if mode is WriteMode.REPLACE:
                cursor.execute(f"DELETE FROM {target} WHERE 1 = 1")  # nosec B608
            for batch in [] if first is None else chain([first], batches):
                if mode is WriteMode.MERGE:
                    self._delete_keyed(cursor, table, key, key_positions, batch)
                self._insert(cursor, table, columns, batch)
                written += len(batch)
            self._commit(connection)
        except ConfigurationError:
            self._rollback(connection)
            raise
        except Exception as error:
            self._rollback(connection)
            raise ConfigurationError(
                f"Writing to {table} failed: {error}",
                context={"table": table, "mode": mode.value},
                cause=error,
            ) from error
        return written

    def _delete_keyed(
        self,
        cursor: Any,
        table: str,
        key: Sequence[str],
        positions: Sequence[int],
        batch: list[Sequence[Any]],
    ) -> None:
        keys = [[row[position] for position in positions] for row in batch]
        if any(value is None for values in keys for value in values):
            raise ConfigurationError(
                f"A row written to {table} has no value for its key ({', '.join(key)}); "
                "a merge cannot tell which row it replaces",
                context={"table": table, "key": list(key)},
            )
        dialect = self.dialect
        names = [dialect.identifier(column) for column in key]
        for chunk in _statement_chunks(keys, len(key), dialect.max_params):
            markers = iter(dialect.markers(len(chunk) * len(key)))
            if len(key) == 1:
                match = f"{names[0]} IN ({', '.join(next(markers) for _ in chunk)})"
            else:
                match = " OR ".join(
                    "(" + " AND ".join(f"{name} = {next(markers)}" for name in names) + ")"
                    for _ in chunk
                )
            statement = f"DELETE FROM {dialect.identifier(table)} WHERE {match}"  # nosec B608
            cursor.execute(
                statement, dialect.bound([value for values in chunk for value in values])
            )

    def _not_held(
        self,
        table: str,
        columns: Sequence[str],
        rows: Iterable[Sequence[Any]],
        key: Sequence[str],
    ) -> list[Sequence[Any]]:
        positions = [columns.index(column) for column in key]
        held = self.held_keys(table, key)
        return [row for row in rows if tuple(row[p] for p in positions) not in held]

    def held_keys(self, table: str, key: Sequence[str]) -> set[tuple[Any, ...]]:
        """The *key* values *table* holds; none when there is no such table."""
        if self._held_columns(self._open(), table) is None:
            return set()
        names = ", ".join(self.dialect.identifier(column) for column in key)
        query = f"SELECT {names} FROM {self.dialect.identifier(table)}"  # nosec B608
        return {tuple(row.values()) for row in self.read(query)}

    def _held_columns(self, connection: Any, table: str) -> list[str] | None:
        """The columns *table* has, or None when the database has no such table."""
        probe = f"SELECT * FROM {self.dialect.identifier(table)} WHERE 1 = 0"  # nosec B608
        try:
            cursor = self._cursor(connection)
            cursor.execute(probe)
            names = [column[0] for column in cursor.description]
            cursor.close()
            return names
        except Exception as error:
            if not self._is_missing_table(error):
                raise ConfigurationError(
                    f"Cannot read table {table}: {error}", context={"table": table}, cause=error
                ) from error
            logger.debug("Taking %s as absent: %s", table, error)
            return None
        finally:
            self._rollback(connection)

    def _is_missing_table(self, error: Exception) -> bool:
        """Whether *error* says the table does not exist, and nothing worse."""
        message = str(error).lower()
        return any(words in message for words in _MISSING_TABLE)

    @staticmethod
    def _rollback(connection: Any) -> None:
        try:
            connection.rollback()
        except Exception as error:
            logger.debug("Nothing to roll back: %s", error)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _close_quietly(cursor: Any) -> None:
    if cursor is None:
        return
    try:
        cursor.close()
    except Exception as error:
        logger.debug("Could not close a cursor: %s", error)


def _refuse_missing_columns(
    table: str, columns: Sequence[str], held: Sequence[str], *, exact: bool
) -> None:
    """Refuse a write to a table lacking a column; a bare name is matched in any case."""
    have = set(held) if exact else {name.lower() for name in held}
    missing = [column for column in columns if (column if exact else column.lower()) not in have]
    if missing:
        raise ConfigurationError(
            f"Table {table} has no column {', '.join(missing)}; add it, or write to a new table",
            context={"table": table, "missing": missing},
        )


def _statement_chunks(
    rows: Sequence[Sequence[Any]], width: int, max_params: int
) -> Iterator[Sequence[Sequence[Any]]]:
    """*rows* in runs short enough that one statement binds at most *max_params* values."""
    size = max(1, max_params // max(1, width))
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _batches(rows: Iterable[Sequence[Any]], size: int) -> Iterator[list[Sequence[Any]]]:
    batch: list[Sequence[Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
