"""A query's rows, kept as staging documents the first stage walks like any others."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import IO, Any

from agent_actions.connections import Connector, Row, json_safe

logger = logging.getLogger(__name__)

DEFAULT_SNAPSHOT_FILES = 8
REMOTE_CACHE_DIR = "_remote_cache"

# Start nodes run in threads and may share one source.
_SNAPSHOT_LOCK = threading.Lock()


def snapshot_fingerprint(connection: str, query: str, settings: Mapping[str, Any]) -> str:
    """What names a snapshot: the same query through the same connection settings.

    *settings* are the connection's entry with its ``${NAME}`` values read in,
    except a credential, which is hashed as its reference, never as its value.
    """
    written = json.dumps(dict(settings), sort_keys=True, default=str)
    return hashlib.sha256(f"{connection}\n{query}\n{written}".encode()).hexdigest()[:12]


def drop_database_snapshots(agent_folder: Path) -> None:
    """Forget every query snapshot under *agent_folder*, so the next run reads again."""
    shutil.rmtree(agent_folder / REMOTE_CACHE_DIR / "database", ignore_errors=True)


def snapshot_query(
    connector: Connector, query: str, snapshot_dir: Path, files: int = DEFAULT_SNAPSHOT_FILES
) -> int:
    """Write the rows of *query* under *snapshot_dir*, spread over at most *files* files.

    A row's file is chosen by its content, not its place in the result: a record
    is answered again when the file holding it changes name, so a row added or
    removed must not move the rows after it.

    The files are written beside *snapshot_dir* and moved into place together, so
    a read that stops partway leaves no directory a later run would take for a
    whole snapshot. A snapshot another thread wrote meanwhile is kept.
    """
    with _SNAPSHOT_LOCK:
        if snapshot_dir.exists():
            return 0
        partial = snapshot_dir.with_name(f"{snapshot_dir.name}.partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        total = _write_documents(connector, query, partial, files)
        os.replace(partial, snapshot_dir)
    logger.info("Read %d rows into %s", total, snapshot_dir)
    return total


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
    text = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return int(hashlib.sha256(text.encode()).hexdigest(), 16) % files
