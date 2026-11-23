"""Shared logger, limits and typing host for the SQLiteBackend mixins."""

import logging
import sqlite3
import threading
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from agent_actions.storage.backend import StorageBackend

# Named for the public module so records keep the logger name they had before the split.
logger = logging.getLogger("agent_actions.storage.backends.sqlite_backend")

_SQL_MAX_PARAMS = 900
"""Below SQLite's 999-parameter default, so an IN (...) list is chunked rather than rejected."""

if TYPE_CHECKING:

    class SQLiteHost(StorageBackend):
        """What the mixins use from ``SQLiteBackend``; seen by the type checker only."""

        db_path: Path
        workflow_name: str
        _connection: sqlite3.Connection | None
        _readonly: bool
        _lock: threading.RLock
        _claimed_source_guids_this_run: dict[str, str]
        _dictionaries: dict[int, bytes]

        @property
        @abstractmethod
        def connection(self) -> sqlite3.Connection: ...

        @abstractmethod
        def _validate_identifier(self, name: str, field: str) -> str: ...

else:
    SQLiteHost = object
