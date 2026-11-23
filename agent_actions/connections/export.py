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
    row. A field holding a list or an object is written as JSON text.
    """
    columns = [IDENTITY_COLUMN, *carry]
    flat: list[dict[str, Any]] = []
    for record in records:
        content = record.get("content")
        if record.get("_state") in _NOT_OUTPUT_STATES or not isinstance(content, dict):
            continue
        answer = content.get(action)
        if not isinstance(answer, dict):
            continue
        clash = sorted(set(answer) & set(columns[: len(carry) + 1]))
        if clash:
            raise ConfigurationError(
                f"Action '{action}' has a field named like a column written beside "
                f"its own: {', '.join(clash)}; drop it from 'carry' or rename the field",
                context={"action": action, "fields": clash},
            )
        source = content.get("source")
        source = source if isinstance(source, dict) else {}
        row = {IDENTITY_COLUMN: record.get(IDENTITY_COLUMN)}
        row.update({name: source.get(name) for name in carry})
        row.update(answer)
        columns.extend(name for name in answer if name not in columns)
        flat.append(row)
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
    if output.mode is WriteMode.MERGE:
        rows = _last_row_per_key(columns, rows, output.key, output.table)
    if not rows and output.mode is not WriteMode.REPLACE:
        return 0
    return connector.write(
        output.table,
        columns,
        rows,
        mode=output.mode,
        key=output.key,
        types=column_types(columns, rows),
    )


def _last_row_per_key(
    columns: list[str], rows: list[tuple[Any, ...]], key: list[str], table: str
) -> list[tuple[Any, ...]]:
    """One row a key, the last one stored: a merge leaves a table holding no key twice."""
    missing = [name for name in key if name not in columns]
    if missing:
        raise ConfigurationError(
            f"The key of {table} names {', '.join(missing)}, which the rows do not hold "
            f"(they hold {', '.join(columns)})",
            context={"table": table, "key": key},
        )
    positions = [columns.index(name) for name in key]
    latest = {tuple(row[position] for position in positions): row for row in rows}
    return list(latest.values())


def write_outputs(
    backend: StorageBackend,
    declared: Any,
    project_root: Path,
    *,
    actions: Collection[str],
    only_action: str | None = None,
) -> dict[str, int]:
    """Write every output a workflow declares; rows written, keyed by table.

    *actions* are the workflow's own: an output naming any other is refused
    before a table is touched.
    """
    outputs = [
        entry if isinstance(entry, OutputConfig) else OutputConfig(**entry)
        for entry in declared or []
    ]
    unknown = sorted({output.action for output in outputs} - set(actions))
    if unknown:
        raise ConfigurationError(
            f"outputs name {', '.join(unknown)}, which this workflow does not run "
            f"(it runs {', '.join(actions)})",
            context={"unknown": unknown},
        )
    written: dict[str, int] = {}
    for output in outputs:
        if only_action and output.action != only_action:
            continue
        with open_connection(output.connection, project_root) as connector:
            written[output.table] = write_output(backend, output, connector)
        logger.info("Wrote %d rows of %s to %s", written[output.table], output.action, output.table)
    return written
