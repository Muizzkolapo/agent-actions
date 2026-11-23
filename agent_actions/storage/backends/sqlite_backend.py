"""SQLite storage backend implementation."""

import json  # noqa: F401
import logging
import sqlite3
import string
import threading
import zlib  # noqa: F401
from collections.abc import Collection, Iterable  # noqa: F401
from pathlib import Path
from typing import Any  # noqa: F401

from agent_actions.config.defaults import StorageDefaults
from agent_actions.errors.classification import mark_action_fatal
from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.errors.processing import SerializationError  # noqa: F401
from agent_actions.errors.validation import DataValidationError  # noqa: F401
from agent_actions.logging.diagnostics import DIAGNOSTIC  # noqa: F401
from agent_actions.record.reasons import GUARD_SKIP  # noqa: F401
from agent_actions.storage.backend import (  # noqa: F401
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SUCCESS,
    NODE_LEVEL_RECORD_ID,
    VALID_DISPOSITIONS,
    Disposition,
    DispositionRow,
    StorageBackend,
    batch_file_names_key,
)
from agent_actions.storage.backends.sqlite.checkpoints import SQLiteCheckpointMixin
from agent_actions.storage.backends.sqlite.codec import SQLitePayloadCodecMixin
from agent_actions.storage.backends.sqlite.common import _SQL_MAX_PARAMS  # noqa: F401
from agent_actions.storage.backends.sqlite.dispositions import SQLiteDispositionMixin
from agent_actions.storage.backends.sqlite.maintenance import SQLiteMaintenanceMixin
from agent_actions.storage.backends.sqlite.metadata import SQLiteMetadataMixin
from agent_actions.storage.backends.sqlite.prompt_traces import SQLitePromptTraceMixin
from agent_actions.storage.backends.sqlite.source_data import SQLiteSourceDataMixin
from agent_actions.storage.backends.sqlite.target_data import SQLiteTargetDataMixin
from agent_actions.utils import deep_json  # noqa: F401

# The F401 names above are kept importable from this module, where they lived before
# the table-level methods moved into agent_actions.storage.backends.sqlite.

logger = logging.getLogger(__name__)


class SQLiteBackend(
    SQLiteSourceDataMixin,
    SQLiteTargetDataMixin,
    SQLiteMetadataMixin,
    SQLiteDispositionMixin,
    SQLiteCheckpointMixin,
    SQLitePromptTraceMixin,
    SQLiteMaintenanceMixin,
    SQLitePayloadCodecMixin,
    StorageBackend,
):
    """SQLite-based storage backend using a single DB file per workflow."""

    SOURCE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS source_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            relative_path TEXT NOT NULL,
            source_guid TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            repeat_of_source_guid TEXT DEFAULT NULL,
            UNIQUE(relative_path, source_guid)
        )
    """

    TARGET_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS target_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            data TEXT NOT NULL,
            record_count INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(action_name, relative_path)
        )
    """

    DISPOSITION_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS record_disposition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_name TEXT NOT NULL,
            record_id TEXT NOT NULL,
            disposition TEXT NOT NULL,
            reason TEXT,
            detail TEXT,
            relative_path TEXT,
            input_snapshot TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(action_name, record_id, disposition)
        )
    """

    SOURCE_INDEX_SQL = """
        CREATE INDEX IF NOT EXISTS idx_source_path ON source_data(relative_path)
    """
    SOURCE_INDEX_REPEAT_OF_SQL = """
        CREATE INDEX IF NOT EXISTS idx_source_repeat_of ON source_data(repeat_of_source_guid)
    """
    DISPOSITION_INDEX_ACTION_SQL = """
        CREATE INDEX IF NOT EXISTS idx_disp_action ON record_disposition(action_name)
    """
    DISPOSITION_INDEX_ACTION_DISP_SQL = """
        CREATE INDEX IF NOT EXISTS idx_disp_action_disp ON record_disposition(action_name, disposition)
    """
    DISPOSITION_INDEX_ACTION_RECORD_SQL = """
        CREATE INDEX IF NOT EXISTS idx_disp_action_record ON record_disposition(action_name, record_id)
    """

    PROMPT_TRACE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS prompt_trace (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_name TEXT NOT NULL,
            record_id TEXT NOT NULL,      -- prepare-time target_id (re-minted per run)
            source_guid TEXT,             -- durable input identity; joins record_disposition.record_id
            run_id TEXT,                  -- workflow run that wrote this row
            attempt INTEGER NOT NULL DEFAULT 0,
            compiled_prompt TEXT NOT NULL,
            llm_context TEXT,
            response_text TEXT,
            model_name TEXT,
            model_vendor TEXT,
            run_mode TEXT,
            prompt_length INTEGER,
            context_length INTEGER,
            response_length INTEGER,
            answered_under TEXT,          -- JSON: the config this record was answered under
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(action_name, record_id, attempt)
        )
    """
    # Rows are insert-only and committed ids never reused, so a trace's dictionary cannot change under it.
    TRACE_DICTIONARY_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS prompt_trace_dictionary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            data BLOB NOT NULL,
            UNIQUE(action_name, column_name)
        )
    """
    TRACE_INDEX_ACTION_SQL = """
        CREATE INDEX IF NOT EXISTS idx_trace_action ON prompt_trace(action_name)
    """
    TRACE_INDEX_ACTION_RECORD_SQL = """
        CREATE INDEX IF NOT EXISTS idx_trace_action_record ON prompt_trace(action_name, record_id)
    """
    TRACE_INDEX_ACTION_SOURCE_SQL = """
        CREATE INDEX IF NOT EXISTS idx_trace_action_source ON prompt_trace(action_name, source_guid)
    """

    CHECKPOINT_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS checkpoint_output (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            source_guid TEXT,
            record_data TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(action_name, relative_path, source_guid)
        )
    """
    CHECKPOINT_INDEX_SQL = """
        CREATE INDEX IF NOT EXISTS idx_checkpoint_action
        ON checkpoint_output(action_name, relative_path)
    """

    # Required columns per table — missing ones are ALTER-added on open
    # (see _enforce_schema; tables are never dropped or rebuilt).
    _REQUIRED_COLUMNS: dict[str, set[str]] = {
        "source_data": {
            "relative_path",
            "source_guid",
            "data",
            "created_at",
            "repeat_of_source_guid",
        },
        "target_data": {"action_name", "relative_path", "data", "record_count", "created_at"},
        "record_disposition": {
            "action_name",
            "record_id",
            "disposition",
            "reason",
            "relative_path",
            "input_snapshot",
            "detail",
            "created_at",
        },
        "prompt_trace": {
            "action_name",
            "record_id",
            "source_guid",
            "run_id",
            "attempt",
            "compiled_prompt",
            "llm_context",
            "response_text",
            "model_name",
            "model_vendor",
            "run_mode",
            "prompt_length",
            "context_length",
            "response_length",
            "answered_under",
            "created_at",
        },
    }

    # Allowlist for identifiers (action names, relative paths).
    # Restrictive as defense-in-depth; all SQL is parameterized.
    _VALID_IDENTIFIER_CHARS = set(string.ascii_letters + string.digits + "_-./ ")

    METADATA_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS workflow_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """

    def __init__(self, db_path: str, workflow_name: str):
        """Initialize SQLite backend."""
        super().__init__()
        self.db_path = Path(db_path)
        self.workflow_name = workflow_name
        self._connection: sqlite3.Connection | None = None
        self._readonly: bool = False
        self._lock = (
            threading.RLock()
        )  # Serialize write operations; RLock allows re-entry from connection property
        self._claimed_source_guids_this_run: dict[str, str] = {}
        self._dictionaries: dict[int, bytes] = {}

    @classmethod
    def create(cls, **kwargs) -> "SQLiteBackend":
        """Factory classmethod for SQLiteBackend construction.

        Required kwargs:
            db_path: Path to the SQLite database file.
            workflow_name: Name of the workflow.
        """
        db_path = kwargs.pop("db_path")
        workflow_name = kwargs.pop("workflow_name")
        if kwargs:
            raise ConfigValidationError(
                f"Unknown kwargs for SQLiteBackend: {list(kwargs)}",
                context={"unknown_kwargs": list(kwargs)},
            )
        return cls(str(db_path), workflow_name)

    @classmethod
    def create_readonly(cls, db_path: str | Path) -> "SQLiteBackend":
        """Create a read-only instance for scanning. Do not call initialize()."""
        import urllib.parse

        db_path = Path(db_path)
        instance = cls(str(db_path), db_path.stem)
        instance._readonly = True

        posix_path = instance.db_path.as_posix()
        if not posix_path.startswith("/"):
            posix_path = "/" + posix_path
        encoded_path = urllib.parse.quote(posix_path, safe="/:")

        ro_uri = f"file://{encoded_path}?mode=ro"
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(ro_uri, uri=True)
            conn.row_factory = sqlite3.Row
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        except sqlite3.OperationalError:
            if conn is not None:
                conn.close()
            conn = sqlite3.connect(f"file://{encoded_path}?immutable=1", uri=True)
            conn.row_factory = sqlite3.Row

        instance._connection = conn
        return instance

    def _validate_identifier(self, name: str, field: str) -> str:
        """Validate and POSIX-normalize an identifier to prevent injection.

        Raises:
            ValueError: If identifier contains invalid characters.
        """
        if not name or not name.strip():
            raise ValueError(f"Empty {field} not allowed")
        name = name.strip()
        name = name.replace("\\", "/")
        if ".." in name.split("/"):
            raise ValueError(f"Path traversal ('..') not allowed in {field}")
        if not all(c in self._VALID_IDENTIFIER_CHARS for c in name):
            invalid = set(name) - self._VALID_IDENTIFIER_CHARS
            raise ValueError(f"Invalid characters in {field}: {invalid}")
        return name

    def stored_path(self, relative_path: str) -> str:
        try:
            return self._validate_identifier(relative_path, "relative_path")
        except ValueError:
            # Refused on write too, so it is listed under no name at all.
            return relative_path

    @property
    def backend_type(self) -> str:
        """Return the backend type identifier."""
        return "sqlite"

    @classmethod
    def paths_to_wipe(cls, io_dir: Path) -> list[Path]:
        store = io_dir / "store"
        return [store] if store.exists() else []

    def _open_connection(self) -> None:
        """Create and configure the database connection."""
        if self._connection is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=StorageDefaults.SQLITE_LOCK_TIMEOUT_SECONDS,
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        # Under WAL, NORMAL still survives a process crash; only an OS crash or power
        # loss can drop the last commits, and the database stays consistent either way.
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.row_factory = sqlite3.Row

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the database connection. Raises if not initialized."""
        with self._lock:
            if self._connection is None:
                # The store serves every file, so no one file failed.
                raise mark_action_fatal(
                    RuntimeError("Backend not initialized. Call initialize() first.")
                )
            return self._connection

    def initialize(self) -> None:
        """Create connection, enforce schema, create tables and indexes."""
        if self._readonly:
            raise RuntimeError("Cannot initialize a read-only backend instance.")
        with self._lock:
            self._open_connection()
            cursor = self.connection.cursor()
            try:
                self._enforce_schema(cursor)
                cursor.execute(self.SOURCE_TABLE_SQL)
                cursor.execute(self.TARGET_TABLE_SQL)
                cursor.execute(self.DISPOSITION_TABLE_SQL)
                cursor.execute(self.SOURCE_INDEX_SQL)
                cursor.execute(self.SOURCE_INDEX_REPEAT_OF_SQL)
                cursor.execute(self.DISPOSITION_INDEX_ACTION_SQL)
                cursor.execute(self.DISPOSITION_INDEX_ACTION_DISP_SQL)
                cursor.execute(self.DISPOSITION_INDEX_ACTION_RECORD_SQL)
                cursor.execute(self.PROMPT_TRACE_TABLE_SQL)
                cursor.execute(self.TRACE_INDEX_ACTION_SQL)
                cursor.execute(self.TRACE_INDEX_ACTION_RECORD_SQL)
                cursor.execute(self.TRACE_INDEX_ACTION_SOURCE_SQL)
                cursor.execute(self.TRACE_DICTIONARY_TABLE_SQL)
                cursor.execute(self.CHECKPOINT_TABLE_SQL)
                cursor.execute(self.CHECKPOINT_INDEX_SQL)
                cursor.execute(self.METADATA_TABLE_SQL)
                self.connection.commit()
                logger.info(
                    "Initialized SQLite storage backend: %s",
                    self.db_path,
                    extra={"workflow_name": self.workflow_name},
                )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to initialize SQLite backend: %s",
                    e,
                    extra={"db_path": str(self.db_path), "workflow_name": self.workflow_name},
                )
                raise

    def _enforce_schema(self, cursor: sqlite3.Cursor) -> None:
        """Add missing columns to existing tables via ALTER TABLE.

        Never drops tables — user data must survive framework upgrades.
        Only adds columns; does not remove or rename existing columns.
        """
        for table_name, required in self._REQUIRED_COLUMNS.items():
            # Quote identifier to prevent SQL injection (table_name is from
            # hardcoded _REQUIRED_COLUMNS keys, but defense-in-depth)
            quoted_table = f'"{table_name}"'
            # PRAGMA does not support quoted identifiers — but table_name
            # is safe (from hardcoded _REQUIRED_COLUMNS keys, not user input)
            cursor.execute(f"PRAGMA table_info({table_name})")
            rows = cursor.fetchall()
            if not rows:
                continue  # table doesn't exist yet — CREATE TABLE handles it

            existing = {row[1] for row in rows}
            missing = required - existing
            if missing:
                columns_to_add = sorted(missing)
                for column in columns_to_add:
                    logger.debug(
                        "Table '%s' missing column '%s' — adding via ALTER TABLE",
                        table_name,
                        column,
                    )
                    # Quote column name for safety; TEXT DEFAULT NULL is
                    # the most permissive — application code handles types
                    quoted_col = f'"{column}"'
                    cursor.execute(
                        f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_col} TEXT DEFAULT NULL"
                    )
                logger.info(
                    "Schema migration complete for '%s': added %d column(s): %s",
                    table_name,
                    len(columns_to_add),
                    columns_to_add,
                )

    def close(self) -> None:
        """Close the database connection and clear caches."""
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                    logger.debug(
                        "Closed SQLite connection: %s",
                        self.db_path,
                        extra={"workflow_name": self.workflow_name},
                    )
                except sqlite3.Error as e:
                    logger.warning(
                        "Error closing SQLite connection: %s",
                        e,
                        extra={"workflow_name": self.workflow_name},
                    )
                finally:
                    self._connection = None
        super().close()
