"""Write an action's stored records to a database table, one row a record."""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Iterable, Iterator
from pathlib import Path
from typing import Any

from agent_actions.config.schema import OUTPUT_IDENTITY_COLUMN as IDENTITY_COLUMN
from agent_actions.config.schema import OutputConfig
from agent_actions.connections import ColumnType, Connector, WriteMode, open_connection
from agent_actions.connections.base import quoted_identifier
from agent_actions.connections.dbapi import key_text
from agent_actions.errors import ConfigurationError
from agent_actions.record.state import CASCADE_BLOCKING_STATES, RecordState
from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)

_NOT_OUTPUT_STATES = frozenset(
    state.value for state in CASCADE_BLOCKING_STATES | {RecordState.GUARD_SKIPPED}
)


def output_table(
    records: Iterable[dict[str, Any]], action: str, carry: list[str]
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """The columns and rows *records* make: identity, carried source fields, the action's fields.

    A record the action left no answer for (guard-skipped, failed above) makes no
    row. A field holding a list or an object is written as JSON text. A carried
    field that no answered record's source holds is refused: it is a misspelling
    more often than a column of nulls.
    """
    columns = [IDENTITY_COLUMN, *carry]
    flat: list[dict[str, Any]] = []
    held: set[str] = set()
    for record in records:
        content = record.get("content")
        if record.get("_state") in _NOT_OUTPUT_STATES or not isinstance(content, dict):
            continue
        answer = content.get(action)
        if not isinstance(answer, dict):
            continue
        beside = {name.lower() for name in columns[: len(carry) + 1]}
        clash = sorted(name for name in answer if name.lower() in beside)
        if clash:
            raise ConfigurationError(
                f"Action '{action}' has a field named like a column written beside "
                f"its own: {', '.join(clash)}; drop it from 'carry' or rename the field",
                context={"action": action, "fields": clash},
            )
        source = content.get("source")
        source = source if isinstance(source, dict) else {}
        held.update(source)
        row = {IDENTITY_COLUMN: record.get(IDENTITY_COLUMN)}
        row.update({name: source.get(name) for name in carry})
        row.update(answer)
        for name in answer:
            if name in columns:
                continue
            twin = next(
                (held_name for held_name in columns if held_name.lower() == name.lower()), None
            )
            if twin is not None:
                raise ConfigurationError(
                    f"Action '{action}' writes both {twin!r} and {name!r}, which most databases "
                    "take as one column; give the fields names that differ in more than case",
                    context={"action": action, "fields": [twin, name]},
                )
            columns.append(name)
        flat.append(row)
    unheld = [name for name in carry if name not in held]
    if flat and unheld:
        raise ConfigurationError(
            f"'carry' names {', '.join(unheld)}, which no record's source holds "
            f"(the source fields are {', '.join(sorted(held)) or 'none'})",
            context={"action": action, "carry": unheld},
        )
    return columns, [tuple(_cell(row.get(name)) for name in columns) for row in flat]


def column_types(columns: list[str], rows: list[tuple[Any, ...]]) -> dict[str, ColumnType]:
    """The type each column's values share; text when they share none or are all null."""
    types: dict[str, ColumnType] = {}
    for position, name in enumerate(columns):
        kinds = {type(row[position]) for row in rows} - {type(None)}
        if kinds == {bool}:
            types[name] = ColumnType.BOOLEAN
        elif kinds == {int}:
            types[name] = ColumnType.INTEGER
        elif kinds and kinds <= {int, float}:
            types[name] = ColumnType.REAL
        else:
            types[name] = ColumnType.TEXT
    return types


def _cell(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _stored_records(backend: StorageBackend, action: str) -> Iterator[dict[str, Any]]:
    for relative_path in backend.list_target_files(action):
        yield from backend.read_target(action, relative_path)


def write_output(backend: StorageBackend, output: OutputConfig, connector: Connector) -> int:
    """Write the records *backend* holds for one output and return the row count."""
    columns, rows = output_table(
        _stored_records(backend, output.action), output.action, output.carry
    )
    if not rows and output.mode is not WriteMode.REPLACE:
        return 0
    if output.mode is not WriteMode.REPLACE:
        rows = _one_row_per_key(columns, rows, output)
    return connector.write(
        output.table,
        columns,
        rows,
        mode=output.mode,
        key=output.key,
        types=column_types(columns, rows),
    )


def _one_row_per_key(
    columns: list[str], rows: list[tuple[Any, ...]], output: OutputConfig
) -> list[tuple[Any, ...]]:
    """*rows* with a repeated row dropped; two different rows sharing a key are refused.

    A merge or an append keeps one row a key, so writing both would keep one and
    lose the other without a word: an action that stores several records for one
    source row (an expansion) shares the default key, `source_guid`.
    """
    key, table = output.key, output.table
    missing = [name for name in key if name not in columns]
    if missing:
        raise ConfigurationError(
            f"The key of {table} names {', '.join(missing)}, which the rows do not hold "
            f"(they hold {', '.join(columns)})",
            context={"table": table, "key": key},
        )
    positions = [columns.index(name) for name in key]
    kept: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for row in rows:
        # As text, as the write compares keys: 7 and "7" are one key in the table.
        row_key = tuple(key_text(row[position]) for position in positions)
        held = kept.setdefault(row_key, row)
        if held != row:
            shown = ", ".join(
                f"{name}={value!r}" for name, value in zip(key, row_key, strict=True)
            )
            raise ConfigurationError(
                f"Two records of {output.action} share the key of {table} ({shown}), and "
                f"a {output.mode.value} keeps one row a key. Set 'key' to columns that tell "
                "them apart (carry the source row's own id), or use mode: replace",
                context={"table": table, "key": key, "action": output.action},
            )
    return list(kept.values())


def check_outputs(declared: Any, project_root: Path, *, actions: Collection[str]) -> None:
    """Refuse outputs that cannot be written, before the run pays for any answer.

    An output that names an action the workflow does not run, a connection the
    project does not declare or whose driver is not installed, a name that is not
    a table or column name, or a table another output writes is refused.
    """
    from agent_actions.connections import _connector_class, connection_settings

    outputs = _parsed(declared)
    unknown = sorted({output.action for output in outputs} - set(actions))
    if unknown:
        raise ConfigurationError(
            f"outputs name {', '.join(unknown)}, which this workflow does not run "
            f"(it runs {', '.join(actions)})",
            context={"unknown": unknown},
        )
    for connection in sorted({output.connection for output in outputs}):
        connector = _connector_class(connection, connection_settings(connection, project_root))
        check_driver = getattr(connector, "check_driver", None)
        if check_driver is not None:
            check_driver()
    writers: dict[tuple[str, str], str] = {}
    for output in outputs:
        for name in (output.table, *output.key, *output.carry):
            quoted_identifier(name)
        target = (output.connection, output.table.lower())
        if target in writers:
            raise ConfigurationError(
                f"Both {writers[target]} and {output.action} write {output.table} on "
                f"'{output.connection}', and each write would remove the other's rows; "
                "give each output a table of its own",
                context={"table": output.table, "connection": output.connection},
            )
        writers[target] = output.action


def _parsed(declared: Any) -> list[OutputConfig]:
    return [
        entry if isinstance(entry, OutputConfig) else OutputConfig(**entry)
        for entry in declared or []
    ]


def write_outputs(
    backend: StorageBackend,
    declared: Any,
    project_root: Path,
    *,
    actions: Collection[str],
    only_action: str | None = None,
) -> dict[str, int]:
    """Write every output a workflow declares; rows written, keyed by table.

    A table name two connections share is told apart by its connection.

    *actions* are the workflow's own: an output naming any other is refused
    before a table is touched.
    """
    outputs = _parsed(declared)
    if only_action and only_action not in {output.action for output in outputs}:
        raise ConfigurationError(
            f"No output writes {only_action}; the actions with outputs are "
            f"{', '.join(sorted({output.action for output in outputs}))}",
            context={"action": only_action},
        )
    check_outputs(outputs, project_root, actions=actions)
    tables = [output.table.lower() for output in outputs]
    written: dict[str, int] = {}
    for output in outputs:
        if only_action and output.action != only_action:
            continue
        label = output.table
        if tables.count(output.table.lower()) > 1:
            label = f"{output.table} on {output.connection}"
        with open_connection(output.connection, project_root) as connector:
            written[label] = write_output(backend, output, connector)
        logger.info("Wrote %d rows of %s to %s", written[label], output.action, label)
    return written
