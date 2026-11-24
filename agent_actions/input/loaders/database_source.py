"""A query's rows, kept as staging documents the first stage walks like any others."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import uuid
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import IO, Any

from agent_actions.connections import Connector, Row, json_safe
from agent_actions.errors import ConfigurationError

logger = logging.getLogger(__name__)

# One file keeps the query's order, and gives a File-granularity action every row.
DEFAULT_SNAPSHOT_FILES = 1
REMOTE_CACHE_DIR = "_remote_cache"

# The statements a source may be: anything else could change the data it reads.
_READING_STATEMENT = re.compile(r"^(select|with|values|table)\b", re.IGNORECASE)
_LEADING_NOISE = re.compile(r"^(\s+|--[^\n]*(\n|$)|/\*.*?\*/|\()+", re.DOTALL)

# Start nodes run in threads and may share one source.
_SNAPSHOT_LOCK = threading.Lock()
_refresh_requested = False
_refreshed: set[Path] = set()


def snapshot_fingerprint(
    connection: str, query: str, settings: Mapping[str, Any], files: int = DEFAULT_SNAPSHOT_FILES
) -> str:
    """What names a snapshot: the same query through the same connection settings and files.

    *settings* are the connection's entry with its ``${NAME}`` values read in,
    except a credential, which is hashed as its reference, never as its value.
    """
    written = json.dumps(dict(settings), sort_keys=True, default=str)
    key = f"{connection}\n{query}\n{written}\n{files}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def snapshot_directory(agent_folder: Path, action: str, fingerprint: str) -> Path:
    """Where *action* keeps the snapshot named *fingerprint*."""
    return agent_folder / REMOTE_CACHE_DIR / "database" / action / fingerprint / "data"


def request_refresh() -> None:
    """Have each snapshot this process resolves next read its query again, once."""
    global _refresh_requested
    with _SNAPSHOT_LOCK:
        _refresh_requested = True
        _refreshed.clear()


def forget_refresh_request() -> None:
    """Undo :func:`request_refresh`; for a process that runs more than one command."""
    global _refresh_requested
    with _SNAPSHOT_LOCK:
        _refresh_requested = False
        _refreshed.clear()


def refuse_a_statement_that_writes(query: str) -> None:
    """Refuse a source query that is not a read, before it can reach the database."""
    stripped = _LEADING_NOISE.sub("", query, count=1)
    if not _READING_STATEMENT.match(stripped):
        first = (stripped.split() or ["(nothing)"])[0]
        raise ConfigurationError(
            f"A database data source reads rows, so its sql must be a SELECT (or WITH ... "
            f"SELECT); it starts with {first!r}",
            context={"sql": query},
        )


def snapshot_needs_reading(snapshot_dir: Path) -> bool:
    """Whether *snapshot_dir* must be read: it does not exist, or a refresh asked for it."""
    with _SNAPSHOT_LOCK:
        if not snapshot_dir.exists():
            return True
        return _refresh_requested and snapshot_dir not in _refreshed


def replaces_a_snapshot(snapshot_dir: Path) -> bool:
    """Whether reading *snapshot_dir* would remove a snapshot the action already has."""
    fingerprint_dir = snapshot_dir.parent
    if snapshot_dir.exists() or not fingerprint_dir.parent.is_dir():
        return False
    return any(
        sibling != fingerprint_dir and sibling.is_dir()
        for sibling in fingerprint_dir.parent.iterdir()
    )


def snapshot_query(
    connector: Connector, query: str, snapshot_dir: Path, files: int = DEFAULT_SNAPSHOT_FILES
) -> int:
    """Write the rows of *query* as *snapshot_dir*, spread over at most *files* files.

    With more than one file, a row's file is chosen by its content, not its place
    in the result: a record is answered again when the file holding it changes
    name, so a row added or removed must not move the rows after it.

    The rows are written beside *snapshot_dir* and swapped in only once the read
    has finished, so a read that fails, or a refresh that fails, leaves the
    snapshot that was there. Snapshots of the same action under other queries are
    removed, so going back to one of them reads it again.
    """
    refuse_a_statement_that_writes(query)
    with _SNAPSHOT_LOCK:
        if snapshot_dir.exists() and not (_refresh_requested and snapshot_dir not in _refreshed):
            return 0
        partial = snapshot_dir.with_name(f"{snapshot_dir.name}.partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        try:
            total = _write_documents(connector, query, partial, files)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        _swap_in(partial, snapshot_dir)
        _refreshed.add(snapshot_dir)
        _remove_other_snapshots(snapshot_dir)
    logger.info("Read %d rows into %s", total, snapshot_dir)
    return total


def _swap_in(partial: Path, snapshot_dir: Path) -> None:
    if not snapshot_dir.exists():
        os.replace(partial, snapshot_dir)
        return
    stale = snapshot_dir.with_name(f"{snapshot_dir.name}.stale-{uuid.uuid4().hex[:8]}")
    os.replace(snapshot_dir, stale)
    os.replace(partial, snapshot_dir)
    shutil.rmtree(stale, ignore_errors=True)


def _remove_other_snapshots(snapshot_dir: Path) -> None:
    fingerprint_dir = snapshot_dir.parent
    for sibling in fingerprint_dir.parent.iterdir():
        if sibling != fingerprint_dir and sibling.is_dir():
            shutil.rmtree(sibling, ignore_errors=True)


def _write_documents(connector: Connector, query: str, directory: Path, files: int) -> int:
    """Stream the rows into JSON array documents, one open file a bucket."""
    documents: dict[int, IO[str]] = {}
    total = 0
    with ExitStack() as opened:
        for row in connector.read(query):
            record = {name: json_safe(value) for name, value in row.items()}
            bucket = _bucket(record, files)
            document = documents.get(bucket)
            if document is None:
                path = directory / f"part-{bucket:05d}.json"
                document = opened.enter_context(path.open("w", encoding="utf-8"))
                documents[bucket] = document
                document.write("[")
            else:
                document.write(",\n")
            document.write(json.dumps(record, ensure_ascii=False))
            total += 1
        for document in documents.values():
            document.write("]\n")
    return total


def _bucket(record: Row, files: int) -> int:
    """The file a record goes to, the same whatever order its columns came in."""
    if files == 1:
        return 0
    text = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return int(hashlib.sha256(text.encode()).hexdigest(), 16) % files
