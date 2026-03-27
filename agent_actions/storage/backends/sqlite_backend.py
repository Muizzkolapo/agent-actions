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
from agent_actions.storage.backend import VALID_DISPOSITIONS, Disposition, StorageBackend

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
            relative_path TEXT,
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

    def __init__(self, db_path: str, workflow_name: str):
        """Initialize SQLite backend."""
        self.db_path = Path(db_path)
        self.workflow_name = workflow_name
        self._connection: sqlite3.Connection | None = None
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
        """Create connection, tables, and indexes."""
        with self._lock:
            self._open_connection()
            cursor = self.connection.cursor()
            try:
                cursor.execute(self.SOURCE_TABLE_SQL)
                cursor.execute(self.TARGET_TABLE_SQL)
                cursor.execute(self.DISPOSITION_TABLE_SQL)
                cursor.execute(self.SOURCE_INDEX_SQL)
                cursor.execute(self.DISPOSITION_INDEX_ACTION_SQL)
                cursor.execute(self.DISPOSITION_INDEX_ACTION_DISP_SQL)
                cursor.execute(self.DISPOSITION_INDEX_ACTION_RECORD_SQL)
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

    def write_target(self, action_name: str, relative_path: str, data: list[dict[str, Any]]) -> str:
        """Write target data for a specific node."""
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

    def read_target(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Read target data for a specific node.

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

    def write_source(
        self,
        relative_path: str,
        data: list[dict[str, Any]],
        enable_deduplication: bool = True,
    ) -> str:
        """Write source data with optional deduplication by source_guid."""
        relative_path = self._validate_identifier(relative_path, "relative_path")

        # Pre-filter: build rows list, warn on missing source_guid
        rows: list[tuple[str, str, str]] = []
        for item in data:
            source_guid = item.get("source_guid")
            if not source_guid:
                logger.warning(
                    "Skipping source item without source_guid: %s",
                    relative_path,
                    extra={"workflow_name": self.workflow_name},
                )
                continue
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

                if len(data) > 0 and len(rows) == 0:
                    raise ValueError(
                        f"All {len(data)} source records were dropped for "
                        f"'{relative_path}' (missing source_guid); 0 inserted"
                    )

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
                file_metadata = [row for row in file_metadata if row["relative_path"] == relative_path]

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

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "db_path": str(self.db_path),
            "db_size_bytes": db_size,
            "db_size_human": self._format_size(db_size),
            "source_count": source_count,
            "target_count": target_count,
            "disposition_count": disposition_count,
            "nodes": nodes,
        }

    # ------------------------------------------------------------------
    # Record disposition tracking
    # Read methods (get_disposition, has_disposition) hold self._lock
    # for the full cursor execute/fetch pair.  Write methods
    # (set_disposition, clear_disposition) hold it through the
    # commit/rollback as well.
    # ------------------------------------------------------------------

    def set_disposition(
        self,
        action_name: str,
        record_id: str,
        disposition: str | Disposition,
        reason: str | None = None,
        relative_path: str | None = None,
    ) -> None:
        """Write a disposition record (INSERT OR REPLACE)."""
        action_name = self._validate_identifier(action_name, "action_name")
        record_id = self._validate_identifier(record_id, "record_id")
        if relative_path is not None:
            relative_path = self._validate_identifier(relative_path, "relative_path")
        if disposition not in VALID_DISPOSITIONS:
            raise ValueError(
                f"Invalid disposition '{disposition}'. Valid: {sorted(VALID_DISPOSITIONS)}"
            )

        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO record_disposition
                    (action_name, record_id, disposition, reason, relative_path, created_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (action_name, record_id, disposition, reason, relative_path),
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

    def get_disposition(
        self,
        action_name: str,
        record_id: str | None = None,
        disposition: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query disposition records with optional filters."""
        action_name = self._validate_identifier(action_name, "action_name")

        query = (
            "SELECT action_name, record_id, disposition, reason, relative_path, created_at"
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

    def close(self) -> None:
        """Close the database connection."""
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
