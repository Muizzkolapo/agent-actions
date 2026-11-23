"""``target_data`` reads, writes and previews for the SQLite store."""

import sqlite3
from collections.abc import Iterable
from typing import Any

from agent_actions.storage.backend import (
    batch_file_names_key,
)
from agent_actions.storage.backends.sqlite.codec import SQLitePayloadCodecMixin
from agent_actions.storage.backends.sqlite.common import logger
from agent_actions.utils import deep_json


class SQLiteTargetDataMixin(SQLitePayloadCodecMixin):
    """Reads and writes the ``target_data`` table."""

    def _write_target_raw(
        self, action_name: str, relative_path: str, data: list[dict[str, Any]]
    ) -> str:
        """Store records to SQLite."""
        action_name = self._validate_identifier(action_name, "action_name")
        relative_path = self._validate_identifier(relative_path, "relative_path")

        data_json = deep_json.dumps(data, ensure_ascii=False)
        record_count = len(data)

        with self._lock:
            cursor = self.connection.cursor()
            try:
                stored = self._compress(cursor, action_name, self._TARGET_DATA, data_json)
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO target_data
                    (action_name, relative_path, data, record_count, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (action_name, relative_path, stored, record_count),
                )
                # Left beside the file just written, a checkpoint row would read as an
                # answer given after it, and a resume would put it in place of the row
                # this write stored. Batch writes the file without the online pipeline.
                cursor.execute(
                    "DELETE FROM checkpoint_output WHERE action_name = ? AND relative_path = ?",
                    (action_name, relative_path),
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

        result: list[dict[str, Any]] = self.decode_payload(
            row["data"],
            table="target_data",
            where=f"action '{action_name}' file '{relative_path}'",
        )
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
                f"SELECT action_name, data FROM target_data "  # nosec B608  # only ? placeholders are interpolated
                f"WHERE action_name IN ({placeholders}) AND relative_path = ?",
                (*action_names, relative_path),
            )
            rows = cursor.fetchall()

        result: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result[row["action_name"]] = self.decode_payload(
                row["data"],
                table="target_data",
                where=f"action '{row['action_name']}' file '{relative_path}'",
            )
        return result

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

    def has_target_rows(self, action_name: str) -> bool:
        """One indexed probe; a row stored before record_count existed is measured from its data."""
        action_name = self._validate_identifier(action_name, "action_name")
        with self._lock:
            cursor = self.connection.cursor()
            # CAST: a store migrated to record_count holds it as TEXT, where '0' > 0.
            # SQLite can measure a text row itself; a compressed one is measured below.
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM target_data WHERE action_name = ? "
                "AND COALESCE(CAST(record_count AS INTEGER), "
                "CASE WHEN typeof(data) = 'text' THEN json_array_length(data) END) > 0)",
                (action_name,),
            )
            if cursor.fetchone()[0]:
                return True
            cursor.execute(
                "SELECT relative_path, data FROM target_data WHERE action_name = ? "
                "AND record_count IS NULL AND typeof(data) <> 'text'",
                (action_name,),
            )
            uncounted = cursor.fetchall()
        return any(
            self._count_stored(action_name, row["relative_path"], row["data"]) > 0
            for row in uncounted
        )

    def _count_stored(self, action_name: str, relative_path: str, data: Any) -> int:
        """How many rows a stored file holds, read from the file itself."""
        records = self.decode_payload(
            data, table="target_data", where=f"action '{action_name}' file '{relative_path}'"
        )
        return len(records) if isinstance(records, list) else 1

    def has_target_file(self, action_name: str, relative_path: str) -> bool:
        action_name = self._validate_identifier(action_name, "action_name")
        relative_path = self._validate_identifier(relative_path, "relative_path")
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT 1 FROM target_data WHERE action_name = ? AND relative_path = ? LIMIT 1",
                (action_name, relative_path),
            )
            return cursor.fetchone() is not None

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
                       COALESCE(record_count,
                                CASE WHEN typeof(data) = 'text'
                                     THEN json_array_length(data) END) as record_count,
                       CASE WHEN record_count IS NULL AND typeof(data) <> 'text'
                            THEN data END as uncounted
                FROM target_data
                WHERE action_name = ?
                ORDER BY relative_path
                """,
                (action_name,),
            )
            # A compressed row written without its count is measured from the file itself.
            file_metadata = [
                {
                    "relative_path": row["relative_path"],
                    "record_count": row["record_count"]
                    if row["uncounted"] is None
                    else self._count_stored(action_name, row["relative_path"], row["uncounted"]),
                }
                for row in cursor.fetchall()
            ]

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

                records = self.decode_payload(
                    data_row["data"],
                    table="target_data",
                    where=f"action '{action_name}' file '{file_path}'",
                )
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
                deleted = cursor.rowcount
                self._forget_dictionary(cursor, action_name, self._TARGET_DATA)
                cursor.execute(
                    "DELETE FROM workflow_metadata WHERE key = ?",
                    (batch_file_names_key(action_name),),
                )
                self.connection.commit()
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

    def delete_target_files(self, action_name: str, relative_paths: Iterable[str]) -> int:
        """Delete the files at *relative_paths* an action stores, in one transaction."""
        action_name = self._validate_identifier(action_name, "action_name")
        paths = [self._validate_identifier(path, "relative_path") for path in relative_paths]
        if not paths:
            return 0
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.executemany(
                    "DELETE FROM target_data WHERE action_name = ? AND relative_path = ?",
                    [(action_name, path) for path in paths],
                )
                deleted = cursor.rowcount
                self.connection.commit()
            except sqlite3.Error:
                self.connection.rollback()
                raise
        # A read of a deleted file would otherwise be served from the cache.
        self._reconstruction_cache.clear()
        return deleted
