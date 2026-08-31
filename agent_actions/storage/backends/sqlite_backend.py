"""SQLite storage backend implementation."""

import json
import logging
import sqlite3
import string
import threading
from pathlib import Path
from typing import Any

from agent_actions.config.defaults import StorageDefaults
from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.errors.validation import DataValidationError
from agent_actions.storage.backend import (
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_SUCCESS,
    NODE_LEVEL_RECORD_ID,
    VALID_DISPOSITIONS,
    Disposition,
    DispositionRow,
    StorageBackend,
)

logger = logging.getLogger(__name__)


class SQLiteBackend(StorageBackend):
    """SQLite-based storage backend using a single DB file per workflow."""

    SOURCE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS source_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            relative_path TEXT NOT NULL,
            source_guid TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(action_name, record_id, attempt)
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

    _MAX_TRACE_FIELD_SIZE = 1_048_576  # 1MB

    # Required columns per table — missing ones are ALTER-added on open
    # (see _enforce_schema; tables are never dropped or rebuilt).
    _REQUIRED_COLUMNS: dict[str, set[str]] = {
        "source_data": {"relative_path", "source_guid", "data", "created_at"},
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
            "created_at",
        },
    }

    _INSERT_SOURCE_IGNORE_SQL = """
        INSERT OR IGNORE INTO source_data
        (relative_path, source_guid, data, created_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """
    _INSERT_SOURCE_REPLACE_SQL = """
        INSERT OR REPLACE INTO source_data
        (relative_path, source_guid, data, created_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """

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
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.row_factory = sqlite3.Row

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the database connection. Raises if not initialized."""
        with self._lock:
            if self._connection is None:
                raise RuntimeError("Backend not initialized. Call initialize() first.")
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
                cursor.execute(self.DISPOSITION_INDEX_ACTION_SQL)
                cursor.execute(self.DISPOSITION_INDEX_ACTION_DISP_SQL)
                cursor.execute(self.DISPOSITION_INDEX_ACTION_RECORD_SQL)
                cursor.execute(self.PROMPT_TRACE_TABLE_SQL)
                cursor.execute(self.TRACE_INDEX_ACTION_SQL)
                cursor.execute(self.TRACE_INDEX_ACTION_RECORD_SQL)
                cursor.execute(self.TRACE_INDEX_ACTION_SOURCE_SQL)
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

    def _write_target_raw(
        self, action_name: str, relative_path: str, data: list[dict[str, Any]]
    ) -> str:
        """Store records to SQLite."""
        action_name = self._validate_identifier(action_name, "action_name")
        relative_path = self._validate_identifier(relative_path, "relative_path")

        data_json = json.dumps(data, ensure_ascii=False)
        record_count = len(data)

        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO target_data
                    (action_name, relative_path, data, record_count, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (action_name, relative_path, data_json, record_count),
                )
                self.connection.commit()
                logger.debug(
                    "Wrote %d target records: %s/%s",
                    record_count,
                    action_name,
                    relative_path,
                    extra={"workflow_name": self.workflow_name},
                )
                return f"{action_name}:{relative_path}"
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to write target data: %s",
                    e,
                    extra={
                        "action_name": action_name,
                        "relative_path": relative_path,
                        "workflow_name": self.workflow_name,
                    },
                )
                raise

    def _read_target_raw(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Read raw target data from SQLite.

        Raises:
            FileNotFoundError: If no data exists for the given path.
        """
        action_name = self._validate_identifier(action_name, "action_name")
        relative_path = self._validate_identifier(relative_path, "relative_path")
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT data FROM target_data WHERE action_name = ? AND relative_path = ?",
                (action_name, relative_path),
            )
            row = cursor.fetchone()

        if row is None:
            raise FileNotFoundError(f"No target data found for {action_name}/{relative_path}")

        result: list[dict[str, Any]] = json.loads(row["data"])
        return result

    def _read_target_raw_batch(
        self, action_names: list[str], relative_path: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch raw target data for multiple actions in one batched query."""
        if not action_names:
            return {}
        placeholders = ",".join("?" for _ in action_names)
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                f"SELECT action_name, data FROM target_data "
                f"WHERE action_name IN ({placeholders}) AND relative_path = ?",
                (*action_names, relative_path),
            )
            rows = cursor.fetchall()

        result: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result[row["action_name"]] = json.loads(row["data"])
        return result

    def _save_metadata_raw(self, key: str, value: str) -> None:
        """Store a metadata key-value pair. Latest value wins (INSERT OR REPLACE)."""
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO workflow_metadata (key, value, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (key, value),
            )
            self.connection.commit()

    def load_metadata(self, key: str) -> str | None:
        """Load a metadata value by key. Returns None if not found."""
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT value FROM workflow_metadata WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
        return row["value"] if row else None

    def delete_metadata(self, key: str) -> bool:
        """Delete a metadata key. Returns True if deleted."""
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM workflow_metadata WHERE key = ?", (key,))
            self.connection.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _escape_like(prefix: str) -> str:
        """Escape SQL LIKE wildcards (`%`, `_`, `\\`) so the prefix is literal."""
        return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def delete_metadata_prefix(self, prefix: str) -> int:
        """Delete all metadata keys starting with `prefix`. Returns count deleted.

        `prefix` is treated literally — SQL LIKE wildcards (`%`, `_`) are escaped.
        """
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "DELETE FROM workflow_metadata WHERE key LIKE ? ESCAPE '\\'",
                (self._escape_like(prefix) + "%",),
            )
            self.connection.commit()
            return cursor.rowcount

    def list_metadata_prefix(self, prefix: str) -> list[str]:
        """Return all metadata keys starting with `prefix`, sorted lexically.

        `prefix` is treated literally — SQL LIKE wildcards (`%`, `_`) are escaped.
        """
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT key FROM workflow_metadata WHERE key LIKE ? ESCAPE '\\' ORDER BY key",
                (self._escape_like(prefix) + "%",),
            )
            return [row["key"] for row in cursor.fetchall()]

    def write_source(
        self,
        relative_path: str,
        data: list[dict[str, Any]],
        enable_deduplication: bool = True,
    ) -> str:
        """Write source data with optional deduplication by source_guid."""
        relative_path = self._validate_identifier(relative_path, "relative_path")

        # A blank source_guid at the storage boundary is an upstream invariant
        # violation, not a routine skip: fail loud (a partial drop is silent data loss).
        rows: list[tuple[str, str, str]] = []
        for index, item in enumerate(data):
            source_guid = item.get("source_guid")
            if not source_guid:
                raise DataValidationError(
                    f"Source record {index} for '{relative_path}' has no source_guid; "
                    f"refusing to drop it silently",
                    context={"relative_path": relative_path, "record_index": index},
                )
            rows.append((relative_path, source_guid, json.dumps(item, ensure_ascii=False)))

        with self._lock:
            cursor = self.connection.cursor()
            try:
                sql = (
                    self._INSERT_SOURCE_IGNORE_SQL
                    if enable_deduplication
                    else self._INSERT_SOURCE_REPLACE_SQL
                )
                cursor.executemany(sql, rows)
                # cursor.rowcount is aggregated across all executemany() iterations by
                # Python's sqlite3 driver; SELECT changes() only reflects the last row.
                inserted_count: int = cursor.rowcount if cursor.rowcount >= 0 else 0

                self.connection.commit()

                skipped_count = len(rows) - inserted_count if enable_deduplication else 0
                dedup_detail = f", {skipped_count} skipped (dedup)" if skipped_count > 0 else ""
                logger.debug(
                    "Wrote source data to %s: %d inserted%s",
                    relative_path,
                    inserted_count,
                    dedup_detail,
                    extra={"workflow_name": self.workflow_name},
                )
                return relative_path
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to write source data: %s",
                    e,
                    extra={
                        "relative_path": relative_path,
                        "workflow_name": self.workflow_name,
                    },
                )
                raise

    def read_source(self, relative_path: str) -> list[dict[str, Any]]:
        """Read source data.

        Raises:
            FileNotFoundError: If no data exists for the given path.
        """
        relative_path = self._validate_identifier(relative_path, "relative_path")
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT data FROM source_data WHERE relative_path = ? ORDER BY id",
                (relative_path,),
            )
            rows = cursor.fetchall()

        if not rows:
            raise FileNotFoundError(f"No source data found for {relative_path}")

        return [json.loads(row["data"]) for row in rows]

    def list_target_files(self, action_name: str) -> list[str]:
        """List all target file paths for a specific node."""
        action_name = self._validate_identifier(action_name, "action_name")
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT DISTINCT relative_path FROM target_data WHERE action_name = ? ORDER BY relative_path",
                (action_name,),
            )
            return [row["relative_path"] for row in cursor.fetchall()]

    def list_source_files(self) -> list[str]:
        """List all source file paths."""
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT DISTINCT relative_path FROM source_data ORDER BY relative_path")
            return [row["relative_path"] for row in cursor.fetchall()]

    def preview_target(
        self,
        action_name: str,
        limit: int = 10,
        offset: int = 0,
        relative_path: str | None = None,
    ) -> dict[str, Any]:
        """Preview target data for a node with pagination."""
        action_name = self._validate_identifier(action_name, "action_name")
        if relative_path is not None:
            relative_path = self._validate_identifier(relative_path, "relative_path")

        limit = min(max(1, limit), 1000)
        offset = max(0, offset)

        with self._lock:
            cursor = self.connection.cursor()

            cursor.execute(
                """
                SELECT relative_path,
                       COALESCE(record_count, json_array_length(data)) as record_count
                FROM target_data
                WHERE action_name = ?
                ORDER BY relative_path
                """,
                (action_name,),
            )
            file_metadata = cursor.fetchall()

            files = [row["relative_path"] for row in file_metadata]

            if relative_path:
                if relative_path not in files:
                    return {
                        "records": [],
                        "total_count": 0,
                        "action_name": action_name,
                        "files": files,
                        "error": f"File '{relative_path}' not found for node '{action_name}'",
                    }
                file_metadata = [
                    row for row in file_metadata if row["relative_path"] == relative_path
                ]

            total_count = sum(row["record_count"] for row in file_metadata)

            paginated_records: list[dict[str, Any]] = []
            skipped = 0
            collected = 0

            for row in file_metadata:
                if collected >= limit:
                    break

                file_path = row["relative_path"]
                file_record_count = row["record_count"]

                if skipped + file_record_count <= offset:
                    skipped += file_record_count
                    continue

                cursor.execute(
                    "SELECT data FROM target_data WHERE action_name = ? AND relative_path = ?",
                    (action_name, file_path),
                )
                data_row = cursor.fetchone()
                if not data_row:
                    continue

                records = json.loads(data_row["data"])
                if records and isinstance(records[0], dict) and "_delta_mode" in records[0]:
                    records = self._reconstruct_from_deltas(action_name, file_path, records)
                for record in records:
                    if skipped < offset:
                        skipped += 1
                        continue

                    if collected < limit:
                        if isinstance(record, dict):
                            paginated_records.append({**record, "_file": file_path})
                        else:
                            paginated_records.append({"_file": file_path, "_value": record})
                        collected += 1
                    else:
                        break

        return {
            "records": paginated_records,
            "total_count": total_count,
            "action_name": action_name,
            "files": files,
            "limit": limit,
            "offset": offset,
        }

    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage statistics (record counts, DB size, per-node breakdown)."""
        with self._lock:
            cursor = self.connection.cursor()

            cursor.execute("SELECT COUNT(*) as count FROM source_data")
            source_count = cursor.fetchone()["count"]

            cursor.execute(
                """
                SELECT action_name, COALESCE(SUM(record_count), 0) as count
                FROM target_data
                GROUP BY action_name
                ORDER BY action_name
                """
            )
            nodes = {row["action_name"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("SELECT COALESCE(SUM(record_count), 0) as count FROM target_data")
            target_count = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM record_disposition")
            disposition_count = cursor.fetchone()["count"]

            cursor.execute(
                """
                SELECT action_name, COUNT(*) as count
                FROM prompt_trace GROUP BY action_name ORDER BY action_name
                """
            )
            trace_stats = {row["action_name"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) as count FROM prompt_trace")
            trace_count = cursor.fetchone()["count"]

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "db_path": str(self.db_path),
            "db_size_bytes": db_size,
            "db_size_human": self._format_size(db_size),
            "source_count": source_count,
            "target_count": target_count,
            "disposition_count": disposition_count,
            "nodes": nodes,
            "trace_count": trace_count,
            "trace_stats": trace_stats,
        }

    # ------------------------------------------------------------------
    # Record disposition tracking
    # Read methods (get_disposition, has_disposition) hold self._lock
    # for the full cursor execute/fetch pair.  Write methods
    # (set_disposition, clear_disposition) hold it through the
    # commit/rollback as well.
    # ------------------------------------------------------------------

    def _validate_disposition_fields(
        self,
        action_name: str,
        record_id: str,
        disposition: str | Disposition,
        relative_path: str | None,
        input_snapshot: str | None,
    ) -> tuple[str, str, str | None, str | None]:
        """Validate and normalize fields shared by set_disposition and set_dispositions_batch.

        Returns (action_name, record_id, relative_path, input_snapshot) after validation.
        """
        action_name = self._validate_identifier(action_name, "action_name")
        record_id = self._validate_identifier(record_id, "record_id")
        if relative_path is not None:
            relative_path = self._validate_identifier(relative_path, "relative_path")
        if disposition not in VALID_DISPOSITIONS:
            raise ValueError(
                f"Invalid disposition '{disposition}'. Valid: {sorted(VALID_DISPOSITIONS)}"
            )
        # Cap input_snapshot at 10KB to prevent storage bloat.
        if input_snapshot and len(input_snapshot) > 10240:
            input_snapshot = json.dumps({"__truncated__": True, "partial": input_snapshot[:8192]})
        return action_name, record_id, relative_path, input_snapshot

    def set_disposition(
        self,
        action_name: str,
        record_id: str,
        disposition: str | Disposition,
        reason: str | None = None,
        relative_path: str | None = None,
        input_snapshot: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Write a disposition record, clearing any prior disposition for this (action, record)."""
        action_name, record_id, relative_path, input_snapshot = self._validate_disposition_fields(
            action_name, record_id, disposition, relative_path, input_snapshot
        )

        with self._lock:
            cursor = self.connection.cursor()
            try:
                # UNIQUE is on (action_name, record_id, disposition), so DELETE first to prevent coexistence.
                cursor.execute(
                    "DELETE FROM record_disposition WHERE action_name = ? AND record_id = ?",
                    (action_name, record_id),
                )
                cursor.execute(
                    """
                    INSERT INTO record_disposition
                    (action_name, record_id, disposition, reason, relative_path,
                     input_snapshot, detail, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        action_name,
                        record_id,
                        disposition,
                        reason,
                        relative_path,
                        input_snapshot,
                        detail,
                    ),
                )
                self.connection.commit()
                logger.debug(
                    "Set disposition: action=%s record=%s disp=%s",
                    action_name,
                    record_id,
                    disposition,
                    extra={"workflow_name": self.workflow_name},
                )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to set disposition: %s",
                    e,
                    extra={
                        "action_name": action_name,
                        "record_id": record_id,
                        "disposition": disposition,
                        "workflow_name": self.workflow_name,
                    },
                )
                raise

    def set_dispositions_batch(
        self,
        dispositions: list[DispositionRow],
    ) -> None:
        """Batch-write dispositions in a single transaction.

        Validates every record before touching the DB — on first invalid
        record the entire batch is rejected with no partial writes.  Uses
        DELETE-then-INSERT (matching set_disposition) to prevent phantom
        coexistence of conflicting dispositions for the same record.
        """
        if not dispositions:
            return

        rows: list[DispositionRow] = []
        seen: set[tuple[str, str, str]] = set()
        for action_name, record_id, disposition, reason, rp, snapshot, detail in dispositions:
            action_name, record_id, rp, snapshot = self._validate_disposition_fields(
                action_name, record_id, disposition, rp, snapshot
            )
            key = (action_name, record_id, disposition)
            if key in seen:
                continue
            seen.add(key)
            rows.append((action_name, record_id, disposition, reason, rp, snapshot, detail))

        with self._lock:
            cursor = self.connection.cursor()
            try:
                # DELETE prior dispositions for each (action_name, record_id) pair,
                # matching set_disposition's DELETE-before-INSERT pattern (P0-5).
                cursor.executemany(
                    "DELETE FROM record_disposition WHERE action_name = ? AND record_id = ?",
                    [(r[0], r[1]) for r in rows],
                )
                cursor.executemany(
                    """
                    INSERT INTO record_disposition
                    (action_name, record_id, disposition, reason, relative_path,
                     input_snapshot, detail, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    rows,
                )
                self.connection.commit()
                logger.debug(
                    "Batch set %d dispositions",
                    len(rows),
                    extra={"workflow_name": self.workflow_name},
                )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to batch set dispositions: %s (count=%d)",
                    e,
                    len(rows),
                    extra={"workflow_name": self.workflow_name},
                )
                raise

    def get_disposition(
        self,
        action_name: str,
        record_id: str | None = None,
        disposition: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query disposition records with optional filters."""
        action_name = self._validate_identifier(action_name, "action_name")

        query = (
            "SELECT action_name, record_id, disposition, reason, relative_path,"
            " input_snapshot, detail, created_at"
            " FROM record_disposition WHERE action_name = ?"
        )
        params: list[str] = [action_name]

        if record_id is not None:
            record_id = self._validate_identifier(record_id, "record_id")
            query += " AND record_id = ?"
            params.append(record_id)
        if disposition is not None:
            query += " AND disposition = ?"
            params.append(disposition)

        query += " ORDER BY id"

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def has_disposition(
        self,
        action_name: str,
        disposition: str,
        record_id: str | None = None,
    ) -> bool:
        """Check whether at least one matching disposition exists."""
        action_name = self._validate_identifier(action_name, "action_name")

        query = "SELECT 1 FROM record_disposition WHERE action_name = ? AND disposition = ?"
        params: list[str] = [action_name, disposition]

        if record_id is not None:
            record_id = self._validate_identifier(record_id, "record_id")
            query += " AND record_id = ?"
            params.append(record_id)

        query += " LIMIT 1"

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            return cursor.fetchone() is not None

    def get_terminal_record_ids(self, action_name: str) -> set[str]:
        """Return record_ids with any gate-terminal disposition for an action."""
        from agent_actions.storage.backend import TERMINAL_DISPOSITIONS

        action_name = self._validate_identifier(action_name, "action_name")
        terminal = tuple(TERMINAL_DISPOSITIONS)
        placeholders = ",".join("?" * len(terminal))
        sql = (
            f"SELECT DISTINCT record_id FROM record_disposition "
            f"WHERE action_name = ? AND disposition IN ({placeholders}) "
            f"AND record_id != ?"
        )
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(sql, (action_name, *terminal, NODE_LEVEL_RECORD_ID))
            return {row["record_id"] for row in cursor.fetchall()}

    def clear_disposition(
        self,
        action_name: str,
        disposition: str | None = None,
        record_id: str | None = None,
    ) -> int:
        """Delete matching disposition records. Returns count deleted."""
        action_name = self._validate_identifier(action_name, "action_name")

        query = "DELETE FROM record_disposition WHERE action_name = ?"
        params: list[str] = [action_name]

        if disposition is not None:
            query += " AND disposition = ?"
            params.append(disposition)
        if record_id is not None:
            record_id = self._validate_identifier(record_id, "record_id")
            query += " AND record_id = ?"
            params.append(record_id)

        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(query, params)
                self.connection.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(
                        "Cleared %d dispositions: action=%s disp=%s record_id=%s",
                        deleted,
                        action_name,
                        disposition,
                        record_id,
                        extra={"workflow_name": self.workflow_name},
                    )
                else:
                    logger.debug(
                        "Cleared %d dispositions: action=%s disp=%s",
                        deleted,
                        action_name,
                        disposition,
                        extra={"workflow_name": self.workflow_name},
                    )
                return deleted
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to clear dispositions: %s",
                    e,
                    extra={
                        "action_name": action_name,
                        "disposition": disposition,
                        "workflow_name": self.workflow_name,
                    },
                )
                raise

    # ------------------------------------------------------------------
    # Checkpoint output (incremental online processing)
    # ------------------------------------------------------------------

    def save_checkpoint_records(
        self,
        action_name: str,
        relative_path: str,
        records: list[dict[str, Any]],
    ) -> None:
        """Append records to the checkpoint output table."""
        if not records:
            return
        action_name = self._validate_identifier(action_name, "action_name")
        relative_path = self._validate_identifier(relative_path, "relative_path")

        # Refuse to checkpoint a namespace that is the compiled JSON Schema instead of
        # LLM output — same seam guard write_target uses on target data.
        records = self._gate_schema_echo_records(action_name, records)

        # Fail loud on blank source_guid: UNIQUE + INSERT OR REPLACE would silently overwrite.
        rows: list[tuple[str, str, str, str]] = []
        for index, r in enumerate(records):
            source_guid = r.get("source_guid")
            if not source_guid:
                raise DataValidationError(
                    f"Checkpoint record {index} for '{action_name}/{relative_path}' "
                    f"has no source_guid; refusing to drop it silently",
                    context={
                        "action_name": action_name,
                        "relative_path": relative_path,
                        "record_index": index,
                    },
                )
            rows.append(
                (
                    action_name,
                    relative_path,
                    source_guid,
                    json.dumps(r, ensure_ascii=False),
                )
            )
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.executemany(
                    "INSERT OR REPLACE INTO checkpoint_output "
                    "(action_name, relative_path, source_guid, record_data) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
                self.connection.commit()
                logger.debug(
                    "Checkpointed %d records for %s/%s",
                    len(records),
                    action_name,
                    relative_path,
                    extra={"workflow_name": self.workflow_name},
                )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to save checkpoint records: %s",
                    e,
                    extra={"workflow_name": self.workflow_name},
                )
                raise

    def read_checkpoint_records(
        self,
        action_name: str,
        relative_path: str,
    ) -> list[dict[str, Any]]:
        """Read all checkpointed records for an action/path."""
        action_name = self._validate_identifier(action_name, "action_name")
        relative_path = self._validate_identifier(relative_path, "relative_path")

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT record_data FROM checkpoint_output "
                "WHERE action_name = ? AND relative_path = ? ORDER BY id",
                (action_name, relative_path),
            )
            return [json.loads(row["record_data"]) for row in cursor.fetchall()]

    def clear_checkpoint_records(self, action_name: str, relative_path: str | None = None) -> None:
        """Delete checkpoint records for an action (optionally scoped to one path)."""
        action_name = self._validate_identifier(action_name, "action_name")

        query = "DELETE FROM checkpoint_output WHERE action_name = ?"
        params: list[str] = [action_name]
        if relative_path is not None:
            relative_path = self._validate_identifier(relative_path, "relative_path")
            query += " AND relative_path = ?"
            params.append(relative_path)

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            deleted = cursor.rowcount
            self.connection.commit()
            if deleted > 0:
                logger.debug(
                    "Cleared %d checkpoint records for %s",
                    deleted,
                    action_name,
                    extra={"workflow_name": self.workflow_name},
                )

    # ------------------------------------------------------------------
    # Prompt trace tracking
    # ------------------------------------------------------------------

    def _cap_trace_field(self, value: str | None) -> str | None:
        """Truncate a trace field to _MAX_TRACE_FIELD_SIZE with a marker."""
        if value and len(value) > self._MAX_TRACE_FIELD_SIZE:
            logger.warning(
                "Truncating trace field from %d bytes to marker (limit %d)",
                len(value),
                self._MAX_TRACE_FIELD_SIZE,
            )
            return json.dumps({"__truncated__": True, "original_length": len(value)})
        return value

    def write_prompt_trace(
        self,
        action_name: str,
        record_id: str,
        compiled_prompt: str,
        llm_context: str | None = None,
        response_text: str | None = None,
        model_name: str | None = None,
        model_vendor: str | None = None,
        run_mode: str | None = None,
        attempt: int = 0,
        source_guid: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Persist the compiled prompt and LLM context for a single record.

        ``record_id`` is the prepare-time target_id; ``source_guid`` is the
        durable identity that response updates and joins key on.
        """
        action_name = self._validate_identifier(action_name, "action_name")
        record_id = self._validate_identifier(record_id, "record_id")
        if source_guid is not None:
            source_guid = self._validate_identifier(source_guid, "source_guid")
        if run_id is not None:
            run_id = self._validate_identifier(run_id, "run_id")

        # Compute lengths from original values before any truncation
        prompt_length = len(compiled_prompt) if compiled_prompt else 0
        context_length = len(llm_context) if llm_context else 0
        response_length = len(response_text) if response_text else 0

        compiled_prompt = self._cap_trace_field(compiled_prompt) or ""
        llm_context = self._cap_trace_field(llm_context)
        response_text = self._cap_trace_field(response_text)

        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO prompt_trace
                    (action_name, record_id, source_guid, run_id, attempt,
                     compiled_prompt, llm_context,
                     response_text, model_name, model_vendor, run_mode,
                     prompt_length, context_length, response_length, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        action_name,
                        record_id,
                        source_guid,
                        run_id,
                        attempt,
                        compiled_prompt,
                        llm_context,
                        response_text,
                        model_name,
                        model_vendor,
                        run_mode,
                        prompt_length,
                        context_length,
                        response_length,
                    ),
                )
                self.connection.commit()
                logger.debug(
                    "Wrote prompt trace: action=%s record=%s attempt=%d",
                    action_name,
                    record_id,
                    attempt,
                    extra={"workflow_name": self.workflow_name},
                )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.warning(
                    "Failed to write prompt trace: %s",
                    e,
                    extra={
                        "action_name": action_name,
                        "record_id": record_id,
                        "workflow_name": self.workflow_name,
                    },
                )

    def update_prompt_trace_response(
        self,
        action_name: str,
        source_guid: str,
        response_text: str,
        parent_source_guid: str | None = None,
    ) -> None:
        """Attach the LLM response to the most recent trace row for a record.

        Both guids are matched rather than ranked: scoped to one action only
        one of them can name a trace, since a ``parent_source_guid`` carried
        down from an earlier expansion names a record this action never
        prepared. A miss is logged — a response with no row is trace loss.
        """
        action_name = self._validate_identifier(action_name, "action_name")
        source_guid = self._validate_identifier(source_guid, "source_guid")
        if parent_source_guid:
            parent_source_guid = self._validate_identifier(parent_source_guid, "parent_source_guid")

        response_length = len(response_text) if response_text else 0
        response_text = self._cap_trace_field(response_text) or ""

        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE prompt_trace
                    SET response_text = ?, response_length = ?
                    WHERE id = (
                        SELECT id FROM prompt_trace
                        WHERE action_name = ? AND source_guid IN (?, ?)
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    (
                        response_text,
                        response_length,
                        action_name,
                        source_guid,
                        parent_source_guid or source_guid,
                    ),
                )
                self.connection.commit()
                if cursor.rowcount > 0:
                    logger.debug(
                        "Updated prompt trace response: action=%s source_guid=%s",
                        action_name,
                        source_guid,
                        extra={"workflow_name": self.workflow_name},
                    )
                else:
                    logger.warning(
                        "No prompt trace row for action=%s source_guid=%s — response not recorded",
                        action_name,
                        source_guid,
                        extra={"workflow_name": self.workflow_name},
                    )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.warning(
                    "Failed to update prompt trace response: %s",
                    e,
                    extra={
                        "action_name": action_name,
                        "source_guid": source_guid,
                        "workflow_name": self.workflow_name,
                    },
                )

    def get_prompt_traces(
        self,
        action_name: str,
        record_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve prompt traces for an action, optionally filtered by record."""
        action_name = self._validate_identifier(action_name, "action_name")

        query = (
            "SELECT action_name, record_id, source_guid, run_id, attempt,"
            " compiled_prompt, llm_context,"
            " response_text, model_name, model_vendor, run_mode,"
            " prompt_length, context_length, response_length, created_at"
            " FROM prompt_trace WHERE action_name = ?"
        )
        params: list[Any] = [action_name]

        if record_id is not None:
            record_id = self._validate_identifier(record_id, "record_id")
            query += " AND record_id = ?"
            params.append(record_id)

        query += " ORDER BY id"

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_prompt_trace_summary(
        self,
        action_name: str,
    ) -> dict[str, Any] | None:
        """Return a representative trace for an action with aggregate stats."""
        action_name = self._validate_identifier(action_name, "action_name")

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT compiled_prompt, model_name, model_vendor,
                       COUNT(*) as trace_count,
                       AVG(prompt_length) as avg_prompt_length,
                       AVG(context_length) as avg_context_length,
                       AVG(response_length) as avg_response_length
                FROM prompt_trace
                WHERE action_name = ?
                GROUP BY action_name
                """,
                (action_name,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return {
            "action_name": action_name,
            "compiled_prompt": row["compiled_prompt"],
            "model_name": row["model_name"],
            "model_vendor": row["model_vendor"],
            "trace_count": row["trace_count"],
            "avg_prompt_length": row["avg_prompt_length"],
            "avg_context_length": row["avg_context_length"],
            "avg_response_length": row["avg_response_length"],
        }

    def preview_prompt_traces(
        self,
        action_name: str,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Paginated access to per-record traces."""
        action_name = self._validate_identifier(action_name, "action_name")
        limit = min(max(1, limit), 1000)
        offset = max(0, offset)

        with self._lock:
            cursor = self.connection.cursor()

            cursor.execute(
                "SELECT COUNT(*) as count FROM prompt_trace WHERE action_name = ?",
                (action_name,),
            )
            total_count = cursor.fetchone()["count"]

            cursor.execute(
                """
                SELECT action_name, record_id, source_guid, run_id, attempt,
                       compiled_prompt, llm_context,
                       response_text, model_name, model_vendor, run_mode,
                       prompt_length, context_length, response_length, created_at
                FROM prompt_trace
                WHERE action_name = ?
                ORDER BY id
                LIMIT ? OFFSET ?
                """,
                (action_name, limit, offset),
            )
            records = [dict(row) for row in cursor.fetchall()]

        return {
            "records": records,
            "total_count": total_count,
            "action_name": action_name,
            "limit": limit,
            "offset": offset,
        }

    def clear_prompt_traces(
        self,
        action_name: str | None = None,
    ) -> int:
        """Delete traces for an action, or all if action_name is None."""
        if action_name is not None:
            action_name = self._validate_identifier(action_name, "action_name")

        with self._lock:
            cursor = self.connection.cursor()
            try:
                if action_name is not None:
                    cursor.execute(
                        "DELETE FROM prompt_trace WHERE action_name = ?",
                        (action_name,),
                    )
                else:
                    cursor.execute("DELETE FROM prompt_trace")
                self.connection.commit()
                deleted = cursor.rowcount
                logger.debug(
                    "Cleared %d prompt traces: action=%s",
                    deleted,
                    action_name or "(all)",
                    extra={"workflow_name": self.workflow_name},
                )
                return deleted
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to clear prompt traces: %s",
                    e,
                    extra={
                        "action_name": action_name,
                        "workflow_name": self.workflow_name,
                    },
                )
                raise

    def delete_target(self, action_name: str) -> int:
        """Delete all target data for a specific action. Returns count deleted."""
        action_name = self._validate_identifier(action_name, "action_name")
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM target_data WHERE action_name = ?",
                    (action_name,),
                )
                self.connection.commit()
                deleted = cursor.rowcount
                logger.debug(
                    "Deleted %d target records for %s",
                    deleted,
                    action_name,
                    extra={"workflow_name": self.workflow_name},
                )
                return deleted
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to delete target for %s: %s",
                    action_name,
                    e,
                    extra={"workflow_name": self.workflow_name},
                )
                raise

    def clear_source_data(self) -> None:
        """Delete all rows from source_data table."""
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute("DELETE FROM source_data")
                self.connection.commit()
                deleted = cursor.rowcount
                logger.info(
                    "Cleared source_data table (%d rows)",
                    deleted,
                    extra={"workflow_name": self.workflow_name},
                )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to clear source_data: %s",
                    e,
                    extra={"workflow_name": self.workflow_name},
                )
                raise

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes as human-readable size."""
        size_bytes = max(0, size_bytes)
        size = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    # ------------------------------------------------------------------
    # Maintenance operations
    # ------------------------------------------------------------------

    def perform_maintenance(
        self,
        prompt_trace_retention_runs: int = StorageDefaults.PROMPT_TRACE_RETENTION_RUNS,
        source_data_ttl_days: int | None = StorageDefaults.SOURCE_DATA_TTL_DAYS,
    ) -> None:
        """Run post-workflow maintenance: WAL checkpoint, disposition cleanup,
        prompt trace retention, and source data TTL.

        All operations are idempotent and safe to run concurrently.
        """
        self._checkpoint_wal()
        self._cleanup_stale_dispositions()
        self._enforce_prompt_trace_retention(prompt_trace_retention_runs)
        if source_data_ttl_days is not None:
            self._enforce_source_data_ttl(source_data_ttl_days)

    def _checkpoint_wal(self) -> None:
        """Checkpoint and truncate the WAL file to reclaim disk space."""
        with self._lock:
            try:
                result = self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                busy, log_pages, checkpointed = result if result else (0, 0, 0)
                if log_pages > 0 or checkpointed > 0:
                    logger.info(
                        "WAL checkpoint: %d pages checkpointed, %d busy",
                        checkpointed,
                        busy,
                        extra={"workflow_name": self.workflow_name},
                    )
                else:
                    logger.debug(
                        "WAL checkpoint: nothing to checkpoint",
                        extra={"workflow_name": self.workflow_name},
                    )
            except sqlite3.Error as e:
                logger.warning(
                    "WAL checkpoint failed (non-fatal): %s",
                    e,
                    extra={"workflow_name": self.workflow_name},
                )

    def _cleanup_stale_dispositions(self) -> None:
        """Remove disposition records for items that completed successfully on re-run.

        When a workflow re-runs, records that previously FAILED may now succeed.
        This removes the old FAILED/EXHAUSTED dispositions for records that have
        a newer SUCCESS disposition, preventing stale data from accumulating.
        """
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    DELETE FROM record_disposition
                    WHERE id IN (
                        SELECT old.id
                        FROM record_disposition old
                        INNER JOIN record_disposition success
                            ON old.action_name = success.action_name
                            AND old.record_id = success.record_id
                        WHERE success.disposition = ?
                          AND old.disposition IN (?, ?)
                          AND old.id < success.id
                    )
                    """,
                    (DISPOSITION_SUCCESS, DISPOSITION_FAILED, DISPOSITION_EXHAUSTED),
                )
                self.connection.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(
                        "Cleaned up %d stale disposition records",
                        deleted,
                        extra={"workflow_name": self.workflow_name},
                    )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.warning(
                    "Disposition cleanup failed (non-fatal): %s",
                    e,
                    extra={"workflow_name": self.workflow_name},
                )

    def _enforce_prompt_trace_retention(self, retention_runs: int) -> None:
        """Delete prompt traces older than the N most recent distinct days.

        Uses DATE(created_at) as the retention boundary, so ``retention_runs``
        effectively means "keep traces from the N most recent calendar days."
        Multiple runs on the same day count as one boundary.
        """
        if retention_runs < 1:
            return
        with self._lock:
            cursor = self.connection.cursor()
            try:
                # Find the Nth most recent distinct run timestamp boundary.
                # Each workflow run writes traces with created_at within the same
                # second range, so we use DATE(created_at) as a run boundary.
                cursor.execute(
                    """
                    SELECT DISTINCT DATE(created_at) as run_date
                    FROM prompt_trace
                    ORDER BY run_date DESC
                    LIMIT 1 OFFSET ?
                    """,
                    (retention_runs - 1,),
                )
                row = cursor.fetchone()
                if row is None:
                    # Fewer runs than retention window — nothing to delete
                    return

                cutoff_date = row[0]
                # Compare created_at directly (not via DATE()) so indexes can be used.
                # cutoff_date is "YYYY-MM-DD"; all timestamps before that date sort lower.
                cursor.execute(
                    "DELETE FROM prompt_trace WHERE created_at < ?",
                    (cutoff_date,),
                )
                self.connection.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(
                        "Pruned %d prompt traces older than %s (keeping %d runs)",
                        deleted,
                        cutoff_date,
                        retention_runs,
                        extra={"workflow_name": self.workflow_name},
                    )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.warning(
                    "Prompt trace retention enforcement failed (non-fatal): %s",
                    e,
                    extra={"workflow_name": self.workflow_name},
                )

    def _enforce_source_data_ttl(self, ttl_days: int) -> None:
        """Delete source_data rows older than ``ttl_days`` days."""
        if ttl_days < 1:
            return
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    DELETE FROM source_data
                    WHERE created_at < datetime('now', '-' || ? || ' days')
                    """,
                    (ttl_days,),
                )
                self.connection.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(
                        "Deleted %d source_data rows older than %d days",
                        deleted,
                        ttl_days,
                        extra={"workflow_name": self.workflow_name},
                    )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.warning(
                    "Source data TTL enforcement failed (non-fatal): %s",
                    e,
                    extra={"workflow_name": self.workflow_name},
                )

    def scan_data(self, preview_limit: int = 20) -> dict[str, Any] | None:
        """Return stats and preview records for the docs scanner."""
        if self._connection is None:
            return None
        with self._lock:
            cursor = self._connection.cursor()

            cursor.execute("SELECT COUNT(*) as count FROM source_data")
            source_count = cursor.fetchone()["count"]

            cursor.execute(
                "SELECT action_name, COALESCE(SUM(record_count), 0) as count "
                "FROM target_data GROUP BY action_name ORDER BY action_name"
            )
            node_counts = {row["action_name"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("SELECT SUM(record_count) as count FROM target_data")
            row = cursor.fetchone()
            target_count = row["count"] if row["count"] else 0

            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

            nodes: dict[str, Any] = {}
            for action_name, record_count in node_counts.items():
                cursor.execute(
                    "SELECT DISTINCT relative_path FROM target_data "
                    "WHERE action_name = ? ORDER BY relative_path",
                    (action_name,),
                )
                files = [r["relative_path"] for r in cursor.fetchall()]

                records: list[dict[str, Any]] = []
                for rp in files:
                    if len(records) >= preview_limit:
                        break
                    try:
                        data = self._read_target_raw(action_name, rp)
                        if not isinstance(data, list):
                            data = [data] if data else []  # type: ignore[unreachable]
                        if data and isinstance(data[0], dict) and "_delta_mode" in data[0]:
                            data = self._reconstruct_from_deltas(action_name, rp, data)
                        for item in data:
                            if len(records) >= preview_limit:
                                break
                            content = item.get("content")
                            if isinstance(content, dict) and action_name in content:
                                ns = content[action_name]
                                if isinstance(ns, dict):
                                    item = {**item, "content": ns}
                                elif ns is None:
                                    item = {**item, "content": {}}
                            records.append({**item, "_file": rp})
                    except (FileNotFoundError, json.JSONDecodeError) as e:
                        logger.debug("Skipping %s/%s in scan: %s", action_name, rp, e)

                # Attach prompt traces by durable identity. A record reaches its
                # prompt by its own source_guid, or — when this action expanded
                # it, minting a guid after the prompt ran — by its parent's.
                try:
                    candidates: set[str] = set()
                    for rec in records:
                        for guid in (rec.get("source_guid"), rec.get("parent_source_guid")):
                            if guid:
                                candidates.add(guid)
                    if candidates:
                        placeholders = ",".join("?" for _ in candidates)
                        cursor.execute(
                            f"SELECT source_guid, compiled_prompt, llm_context, "
                            f"response_text, model_name, model_vendor, run_mode, "
                            f"prompt_length, response_length, attempt "
                            f"FROM prompt_trace "
                            f"WHERE action_name = ? AND source_guid IN ({placeholders})"
                            f" ORDER BY id DESC",
                            [action_name, *candidates],
                        )
                        newest: dict[str, dict[str, Any]] = {}
                        for trace_row in cursor:
                            newest.setdefault(
                                trace_row["source_guid"],
                                {
                                    "compiled_prompt": trace_row["compiled_prompt"],
                                    "llm_context": trace_row["llm_context"],
                                    "response_text": trace_row["response_text"],
                                    "model_name": trace_row["model_name"],
                                    "model_vendor": trace_row["model_vendor"],
                                    "run_mode": trace_row["run_mode"],
                                    "prompt_length": trace_row["prompt_length"],
                                    "response_length": trace_row["response_length"],
                                    "attempt": trace_row["attempt"],
                                },
                            )
                        for rec in records:
                            trace_data = newest.get(rec.get("source_guid") or "") or newest.get(
                                rec.get("parent_source_guid") or ""
                            )
                            if trace_data:
                                rec["_trace"] = trace_data
                except sqlite3.OperationalError:
                    # Missing table, or a pre-migration store opened read-only
                    # (no ALTER pass ran, so identity columns are absent).
                    logger.debug(
                        "No joinable prompt_trace for %s — skipping trace attachment", action_name
                    )

                nodes[action_name] = {
                    "record_count": record_count,
                    "files": files,
                    "preview": records,
                }

            return {
                "db_path": str(self.db_path),
                "db_size": self._format_size(db_size),
                "source_count": source_count,
                "target_count": target_count,
                "nodes": nodes,
            }

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
