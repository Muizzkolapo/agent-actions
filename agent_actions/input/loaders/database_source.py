"""A query's rows, kept as staging documents the first stage walks like any others."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

from agent_actions.connections import Connector, Row, json_safe
from agent_actions.utils.atomic_write import atomic_json_write

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_ROWS = 1000


def snapshot_fingerprint(connection: str, query: str) -> str:
    """What names a snapshot: the same connection and query read the same one."""
    return hashlib.sha256(f"{connection}\n{query}".encode()).hexdigest()[:12]


def snapshot_query(
    connector: Connector, query: str, snapshot_dir: Path, chunk_rows: int = DEFAULT_CHUNK_ROWS
) -> int:
    """Write the rows of *query* under *snapshot_dir*, *chunk_rows* to a file.

    The files are written beside *snapshot_dir* and moved into place together, so
    a fetch that stops partway leaves no directory a later run would take for a
    whole snapshot.
    """
    partial = snapshot_dir.with_name(f"{snapshot_dir.name}.partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    total = 0
    rows = (_as_record(row) for row in connector.read(query))
    for number, chunk in enumerate(_chunks(rows, chunk_rows)):
        atomic_json_write(partial / f"part-{number:05d}.json", chunk, fsync=False)
        total += len(chunk)
    os.replace(partial, snapshot_dir)
    logger.info("Read %d rows into %s", total, snapshot_dir)
    return total


def _as_record(row: Row) -> Row:
    return {name: json_safe(value) for name, value in row.items()}


def _chunks(rows: Iterator[Row], size: int) -> Iterator[list[Row]]:
    while chunk := list(islice(rows, size)):
        yield chunk
