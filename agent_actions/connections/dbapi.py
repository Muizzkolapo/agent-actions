"""One connector over any PEP 249 driver; a database adds how to connect and its dialect."""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from agent_actions.connections.base import (
    ColumnType,
    Connector,
    Row,
    WriteMode,
    json_safe,
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
    # The type a key is cast to so it compares as text, whatever its column holds.
    text_cast: str = "TEXT"
    # Whether two column names that differ only in case are different columns.
    case_sensitive_names: bool = False
    add_column: str = "ALTER TABLE {table} ADD COLUMN {column}"

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

    def as_text(self, name: str) -> str:
        return f"CAST({self.identifier(name)} AS {self.text_cast})"

    def same_name(self, name: str) -> str:
        """*name* as the database tells it from another."""
        return name if self.case_sensitive_names else name.lower()


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
            values = ", ".join(
                "(" + ", ".join(next(markers) for _ in columns) + ")" for _ in chunk
            )
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
        if self.read_only:
            raise ConfigurationError(f"Cannot write {table}: the connection was opened to read")
        if mode is WriteMode.MERGE and not key:
            raise ConfigurationError(
                "A merge needs the key columns that identify a row", context={"table": table}
            )
        missing = [column for column in key if column not in columns]
        if missing:
            raise ConfigurationError(
                f"The key of {table} names {', '.join(missing)}, which the rows do not hold "
                f"(they hold {', '.join(columns)})",
                context={"table": table, "key": list(key)},
            )
        rows = list(rows)
        positions = [columns.index(column) for column in key]
        if key and mode is not WriteMode.REPLACE:
            _refuse_null_keys(table, key, positions, rows)
        if mode is WriteMode.APPEND and key:
            rows = self._not_held(table, rows, positions, key)
        dialect = self.dialect
        target = dialect.identifier(table)
        connection = self._open()
        held = self._held_columns(connection, table)
        if not rows and (held is None or mode is not WriteMode.REPLACE):
            return 0
        written = 0
        try:
            self._begin(connection)
            cursor = self._cursor(connection)
            if held is None:
                kinds = types or {}
                declared = ", ".join(dialect.column(name, kinds.get(name)) for name in columns)
                cursor.execute(f"CREATE TABLE IF NOT EXISTS {target} ({declared})")
            else:
                self._add_missing_columns(cursor, table, columns, held, types or {})
            if mode is WriteMode.REPLACE:
                cursor.execute(f"DELETE FROM {target} WHERE 1 = 1")  # nosec B608
            for batch in _batches(rows, _WRITE_BATCH):
                if mode is WriteMode.MERGE:
                    self._delete_keyed(cursor, table, key, positions, batch)
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

    def _add_missing_columns(
        self,
        cursor: Any,
        table: str,
        columns: Sequence[str],
        held: Sequence[str],
        types: Mapping[str, ColumnType],
    ) -> None:
        """Add each column the rows hold and *table* lacks, as a column that may be null.

        An action's optional field is in no row until an answer carries it, so the
        table made by the first write can lack a column a later write needs.
        """
        dialect = self.dialect
        have = {dialect.same_name(name) for name in held}
        for name in columns:
            if dialect.same_name(name) in have:
                continue
            statement = dialect.add_column.format(
                table=dialect.identifier(table), column=dialect.column(name, types.get(name))
            )
            cursor.execute(statement)
            logger.info("Added column %s to %s", name, table)

    def _delete_keyed(
        self,
        cursor: Any,
        table: str,
        key: Sequence[str],
        positions: Sequence[int],
        batch: list[Sequence[Any]],
    ) -> None:
        """Delete the rows sharing a key with *batch*, keys compared as text.

        Compared as text, a key matches whatever type its column holds: an id an
        earlier write stored as text, or a column made by hand, still matches.
        """
        keys = [[_key_text(row[position]) for position in positions] for row in batch]
        dialect = self.dialect
        names = [dialect.as_text(column) for column in key]
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
        rows: list[Sequence[Any]],
        positions: Sequence[int],
        key: Sequence[str],
    ) -> list[Sequence[Any]]:
        """The rows whose key neither *table* nor an earlier row of *rows* holds."""
        seen = self.held_keys(table, key)
        kept: list[Sequence[Any]] = []
        for row in rows:
            row_key = tuple(_key_text(row[position]) for position in positions)
            if row_key not in seen:
                seen.add(row_key)
                kept.append(row)
        return kept

    def held_keys(self, table: str, key: Sequence[str]) -> set[tuple[str | None, ...]]:
        """The *key* values *table* holds, as text; none when there is no such table."""
        if self._held_columns(self._open(), table) is None:
            return set()
        names = ", ".join(self.dialect.as_text(column) for column in key)
        query = f"SELECT {names} FROM {self.dialect.identifier(table)}"  # nosec B608
        return set(self._read_tuples(query))

    def _read_tuples(self, query: str) -> Iterator[tuple[Any, ...]]:
        """Read *query* as tuples, without the duplicate-name check: casts may share a name."""
        connection = self._open()
        cursor = None
        try:
            cursor = self._cursor(connection)
            cursor.execute(query)
            while batch := cursor.fetchmany(_READ_BATCH):
                for values in batch:
                    yield tuple(values)
        finally:
            _close_quietly(cursor)
            self._rollback(connection)

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


def _refuse_null_keys(
    table: str, key: Sequence[str], positions: Sequence[int], rows: Sequence[Sequence[Any]]
) -> None:
    """Refuse every row with no value for its key, before any statement is sent."""
    if any(row[position] is None for row in rows for position in positions):
        raise ConfigurationError(
            f"A row written to {table} has no value for its key ({', '.join(key)}); "
            "it cannot be told from another row",
            context={"table": table, "key": list(key)},
        )


def _key_text(value: Any) -> str:
    """*value* as text, the way a database casts a stored key to text."""
    safe = json_safe(value)
    return safe if isinstance(safe, str) else json.dumps(safe)


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
