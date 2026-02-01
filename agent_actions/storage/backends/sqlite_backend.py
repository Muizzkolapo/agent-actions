"""SQLite storage backend implementation."""

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional

from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class SQLiteBackend(StorageBackend):
    """
    SQLite-based storage backend.

    Stores source and target data in a single SQLite database file
    per workflow, located at: {workflow}/agent_io/{workflow_name}.db

    Tables:
        source_data: Stores source records with deduplication by source_guid
        target_data: Stores target records organized by node_name

    Thread Safety:
        Uses WAL mode for better concurrency. Each connection should be
        used from a single thread.
    """

    # SQL schema for source_data table
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

    # SQL schema for target_data table
    TARGET_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS target_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            data TEXT NOT NULL,
            record_count INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(node_name, relative_path)
        )
    """

    # Indexes for common query patterns
    SOURCE_INDEX_SQL = """
        CREATE INDEX IF NOT EXISTS idx_source_path ON source_data(relative_path)
    """
    TARGET_INDEX_SQL = """
        CREATE INDEX IF NOT EXISTS idx_target_node_path ON target_data(node_name, relative_path)
    """

    # Valid characters for identifiers (node names, paths)
    _VALID_IDENTIFIER_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./")

    def __init__(self, db_path: str, workflow_name: str):
        """
        Initialize SQLite backend.

        Args:
            db_path: Path to the SQLite database file
            workflow_name: Name of the workflow (used for logging)
        """
        self.db_path = Path(db_path)
        self.workflow_name = workflow_name
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()  # Serialize write operations

    def _validate_identifier(self, name: str, field: str) -> str:
        """
        Validate identifier to prevent injection attacks.

        Args:
            name: The identifier to validate
            field: Field name for error messages

        Returns:
            The validated identifier

        Raises:
            ValueError: If identifier contains invalid characters
        """
        if not name:
            raise ValueError(f"Empty {field} not allowed")
        if not all(c in self._VALID_IDENTIFIER_CHARS for c in name):
            invalid = set(name) - self._VALID_IDENTIFIER_CHARS
            raise ValueError(f"Invalid characters in {field}: {invalid}")
        return name

    @property
    def backend_type(self) -> str:
        """Return the backend type identifier."""
        return "sqlite"

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._connection is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # Allow sharing across threads
                timeout=30.0,  # Wait up to 30s for locks
            )
            # Enable WAL mode for better concurrency
            self._connection.execute("PRAGMA journal_mode=WAL")
            # Enable foreign keys
            self._connection.execute("PRAGMA foreign_keys=ON")
            # Return rows as sqlite3.Row for dict-like access
            self._connection.row_factory = sqlite3.Row

        return self._connection

    def initialize(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(self.SOURCE_TABLE_SQL)
                cursor.execute(self.TARGET_TABLE_SQL)
                cursor.execute(self.SOURCE_INDEX_SQL)
                cursor.execute(self.TARGET_INDEX_SQL)
                self.connection.commit()
                logger.info(
                    "Initialized SQLite storage backend: %s",
                    self.db_path,
                    extra={"workflow_name": self.workflow_name},
                )
            except sqlite3.Error as e:
                logger.error(
                    "Failed to initialize SQLite backend: %s",
                    e,
                    extra={"db_path": str(self.db_path), "workflow_name": self.workflow_name},
                )
                raise

    def write_target(
        self, node_name: str, relative_path: str, data: List[Dict[str, Any]]
    ) -> str:
        """
        Write target data for a specific node.

        Uses INSERT OR REPLACE to handle updates to existing records.

        Args:
            node_name: Name of the processing node
            relative_path: Relative path within target directory
            data: List of records to write

        Returns:
            Identifier string: "node_name:relative_path"
        """
        # Validate inputs
        self._validate_identifier(node_name, "node_name")
        self._validate_identifier(relative_path, "relative_path")

        data_json = json.dumps(data, ensure_ascii=False)
        record_count = len(data)

        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO target_data
                    (node_name, relative_path, data, record_count, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (node_name, relative_path, data_json, record_count),
                )
                self.connection.commit()
                logger.debug(
                    "Wrote %d target records: %s/%s",
                    record_count,
                    node_name,
                    relative_path,
                    extra={"workflow_name": self.workflow_name},
                )
                return f"{node_name}:{relative_path}"
            except sqlite3.Error as e:
                logger.error(
                    "Failed to write target data: %s",
                    e,
                    extra={
                        "node_name": node_name,
                        "relative_path": relative_path,
                        "workflow_name": self.workflow_name,
                    },
                )
                raise

    def read_target(
        self, node_name: str, relative_path: str
    ) -> List[Dict[str, Any]]:
        """
        Read target data for a specific node.

        Args:
            node_name: Name of the processing node
            relative_path: Relative path within target directory

        Returns:
            List of records

        Raises:
            FileNotFoundError: If no data exists for the given path
        """
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT data FROM target_data WHERE node_name = ? AND relative_path = ?",
            (node_name, relative_path),
        )
        row = cursor.fetchone()

        if row is None:
            raise FileNotFoundError(
                f"No target data found for {node_name}/{relative_path}"
            )

        return json.loads(row["data"])

    def write_source(
        self,
        relative_path: str,
        data: List[Dict[str, Any]],
        enable_deduplication: bool = True,
    ) -> str:
        """
        Write source data with optional deduplication.

        Each record is stored individually, keyed by (relative_path, source_guid).
        Deduplication prevents overwriting existing records with the same source_guid.

        Args:
            relative_path: Relative path within source directory
            data: List of source records (each should have source_guid)
            enable_deduplication: If True, skip records with existing source_guids

        Returns:
            Identifier string: relative_path
        """
        # Validate input
        self._validate_identifier(relative_path, "relative_path")

        with self._lock:
            cursor = self.connection.cursor()
            inserted_count = 0
            skipped_count = 0

            try:
                for item in data:
                    source_guid = item.get("source_guid")
                    if not source_guid:
                        logger.warning(
                            "Skipping source item without source_guid: %s",
                            relative_path,
                            extra={"workflow_name": self.workflow_name},
                        )
                        continue

                    data_json = json.dumps(item, ensure_ascii=False)

                    if enable_deduplication:
                        # Use INSERT OR IGNORE to skip duplicates
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO source_data
                            (relative_path, source_guid, data, created_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                            """,
                            (relative_path, source_guid, data_json),
                        )
                        if cursor.rowcount > 0:
                            inserted_count += 1
                        else:
                            skipped_count += 1
                    else:
                        # Use INSERT OR REPLACE to overwrite
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO source_data
                            (relative_path, source_guid, data, created_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                            """,
                            (relative_path, source_guid, data_json),
                        )
                        inserted_count += 1

                self.connection.commit()
                logger.debug(
                    "Wrote source data to %s: %d inserted, %d skipped (dedup)",
                    relative_path,
                    inserted_count,
                    skipped_count,
                    extra={"workflow_name": self.workflow_name},
                )
                return relative_path
            except sqlite3.Error as e:
                logger.error(
                    "Failed to write source data: %s",
                    e,
                    extra={
                        "relative_path": relative_path,
                        "workflow_name": self.workflow_name,
                    },
                )
                raise

    def read_source(self, relative_path: str) -> List[Dict[str, Any]]:
        """
        Read source data.

        Retrieves all records for the given relative_path, ordered by id.

        Args:
            relative_path: Relative path within source directory

        Returns:
            List of source records

        Raises:
            FileNotFoundError: If no data exists for the given path
        """
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT data FROM source_data WHERE relative_path = ? ORDER BY id",
            (relative_path,),
        )
        rows = cursor.fetchall()

        if not rows:
            raise FileNotFoundError(
                f"No source data found for {relative_path}"
            )

        return [json.loads(row["data"]) for row in rows]

    def list_target_files(self, node_name: str) -> List[str]:
        """
        List all target files for a specific node.

        Args:
            node_name: Name of the processing node

        Returns:
            List of relative paths
        """
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT DISTINCT relative_path FROM target_data WHERE node_name = ? ORDER BY relative_path",
            (node_name,),
        )
        return [row["relative_path"] for row in cursor.fetchall()]

    def list_source_files(self) -> List[str]:
        """
        List all source files.

        Returns:
            List of unique relative paths
        """
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT DISTINCT relative_path FROM source_data ORDER BY relative_path"
        )
        return [row["relative_path"] for row in cursor.fetchall()]

    def preview_target(
        self,
        node_name: str,
        limit: int = 10,
        offset: int = 0,
        relative_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Preview target data for a node with pagination.

        Uses streaming to avoid loading all records into memory.
        Records are iterated one file at a time with early exit once
        limit is reached.

        Args:
            node_name: Name of the processing node (action)
            limit: Maximum number of records to return (max 1000)
            offset: Number of records to skip
            relative_path: Optional specific file to preview

        Returns:
            Dict with records, total_count, node_name, and files
        """
        # Enforce maximum limit to prevent memory issues
        limit = min(limit, 1000)

        cursor = self.connection.cursor()

        # Get list of files for this node
        files = self.list_target_files(node_name)

        # If specific file requested, filter to it
        if relative_path:
            if relative_path not in files:
                return {
                    "records": [],
                    "total_count": 0,
                    "node_name": node_name,
                    "files": files,
                    "error": f"File '{relative_path}' not found for node '{node_name}'",
                }
            files_to_query = [relative_path]
        else:
            files_to_query = files

        # Get total count efficiently using stored record_count
        if relative_path:
            cursor.execute(
                "SELECT COALESCE(SUM(record_count), 0) as total FROM target_data WHERE node_name = ? AND relative_path = ?",
                (node_name, relative_path),
            )
        else:
            cursor.execute(
                "SELECT COALESCE(SUM(record_count), 0) as total FROM target_data WHERE node_name = ?",
                (node_name,),
            )
        total_count = cursor.fetchone()["total"]

        # Stream records with pagination - avoid loading all into memory
        paginated_records: List[Dict[str, Any]] = []
        skipped = 0
        collected = 0

        for file_path in files_to_query:
            if collected >= limit:
                break

            cursor.execute(
                "SELECT data FROM target_data WHERE node_name = ? AND relative_path = ?",
                (node_name, file_path),
            )
            row = cursor.fetchone()
            if not row:
                continue

            records = json.loads(row["data"])
            for record in records:
                # Skip records until we reach offset
                if skipped < offset:
                    skipped += 1
                    continue

                # Collect records until we reach limit
                if collected < limit:
                    record["_file"] = file_path
                    paginated_records.append(record)
                    collected += 1
                else:
                    break

        return {
            "records": paginated_records,
            "total_count": total_count,
            "node_name": node_name,
            "files": files,
            "limit": limit,
            "offset": offset,
        }

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dict with database stats and record counts
        """
        cursor = self.connection.cursor()

        # Get source count
        cursor.execute("SELECT COUNT(*) as count FROM source_data")
        source_count = cursor.fetchone()["count"]

        # Get target count and breakdown by node
        cursor.execute(
            """
            SELECT node_name, SUM(record_count) as count
            FROM target_data
            GROUP BY node_name
            ORDER BY node_name
            """
        )
        nodes = {row["node_name"]: row["count"] for row in cursor.fetchall()}

        # Get total target records
        cursor.execute("SELECT SUM(record_count) as count FROM target_data")
        row = cursor.fetchone()
        target_count = row["count"] if row["count"] else 0

        # Get database file size
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "db_path": str(self.db_path),
            "db_size_bytes": db_size,
            "db_size_human": self._format_size(db_size),
            "source_count": source_count,
            "target_count": target_count,
            "nodes": nodes,
        }

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes as human-readable size."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def close(self) -> None:
        """Close the database connection."""
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
