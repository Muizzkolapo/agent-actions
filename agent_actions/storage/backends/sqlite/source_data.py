"""``source_data`` reads, writes and lookups for the SQLite store."""

import sqlite3
from collections.abc import Iterable
from typing import Any

from agent_actions.errors.validation import DataValidationError
from agent_actions.storage.backends.sqlite.codec import SQLitePayloadCodecMixin
from agent_actions.storage.backends.sqlite.common import _SQL_MAX_PARAMS, logger
from agent_actions.utils import deep_json


class SQLiteSourceDataMixin(SQLitePayloadCodecMixin):
    """Reads and writes the ``source_data`` table."""

    _INSERT_SOURCE_IGNORE_SQL = """
        INSERT OR IGNORE INTO source_data
        (relative_path, source_guid, data, repeat_of_source_guid, created_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """
    _INSERT_SOURCE_REPLACE_SQL = """
        INSERT OR REPLACE INTO source_data
        (relative_path, source_guid, data, repeat_of_source_guid, created_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """

    @staticmethod
    def _repeat_of_column(repeat_of: Any) -> str | None:
        """``source_data.repeat_of_source_guid`` for a row: ``""`` when it repeats nothing.

        NULL, as on a row written before the column existed, leaves the answer to the payload.
        """
        if repeat_of is None:
            return ""
        if isinstance(repeat_of, str) and repeat_of:
            return repeat_of
        return None

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
        rows: list[tuple[str, str, str, str | None]] = []
        for index, item in enumerate(data):
            source_guid = item.get("source_guid")
            if not source_guid:
                raise DataValidationError(
                    f"Source record {index} for '{relative_path}' has no source_guid; "
                    f"refusing to drop it silently",
                    context={"relative_path": relative_path, "record_index": index},
                )
            rows.append(
                (
                    relative_path,
                    source_guid,
                    deep_json.dumps(item, ensure_ascii=False),
                    self._repeat_of_column(item.get("repeat_of_source_guid")),
                )
            )

        with self._lock:
            cursor = self.connection.cursor()
            try:
                sql = (
                    self._INSERT_SOURCE_IGNORE_SQL
                    if enable_deduplication
                    else self._INSERT_SOURCE_REPLACE_SQL
                )
                stored = [
                    (
                        path,
                        guid,
                        self._compress(cursor, self._SOURCE_SCOPE, self._SOURCE_DATA, text),
                        repeat_of,
                    )
                    for path, guid, text, repeat_of in rows
                ]
                cursor.executemany(sql, stored)
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
                "SELECT source_guid, data FROM source_data WHERE relative_path = ? ORDER BY id",
                (relative_path,),
            )
            rows = cursor.fetchall()

        if not rows:
            raise FileNotFoundError(f"No source data found for {relative_path}")

        return [
            self.decode_payload(
                row["data"],
                table="source_data",
                where=f"file '{relative_path}' record '{row['source_guid']}'",
            )
            for row in rows
        ]

    def claim_source_guid_for_run(self, source_guid: str, relative_path: str) -> bool:
        """Claim source_guid for this run under relative_path; True if taken elsewhere."""
        with self._lock:
            claimant = self._claimed_source_guids_this_run.get(source_guid)
            if claimant is None:
                self._claimed_source_guids_this_run[source_guid] = relative_path
                return False
            return claimant != relative_path

    def list_source_files(self) -> list[str]:
        """List all source file paths."""
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT DISTINCT relative_path FROM source_data ORDER BY relative_path")
            return [row["relative_path"] for row in cursor.fetchall()]

    def source_files_for_records(self, record_ids: Iterable[str]) -> set[str]:
        """Staging paths, suffix stripped, of the files holding *record_ids*."""
        ids = tuple(dict.fromkeys(record_ids))
        if not ids:
            return set()
        found: set[str] = set()
        with self._lock:
            cursor = self.connection.cursor()
            for start in range(0, len(ids), _SQL_MAX_PARAMS):
                chunk = ids[start : start + _SQL_MAX_PARAMS]
                placeholders = ",".join("?" * len(chunk))
                cursor.execute(
                    f"SELECT DISTINCT relative_path FROM source_data "  # nosec B608  # only ? placeholders are interpolated
                    f"WHERE source_guid IN ({placeholders})",
                    chunk,
                )
                found.update(row["relative_path"] for row in cursor.fetchall())
        return found

    def source_guids_among(self, record_ids: Iterable[str]) -> set[str]:
        """Which of *record_ids* name a stored input row."""
        ids = tuple(dict.fromkeys(record_ids))
        found: set[str] = set()
        with self._lock:
            cursor = self.connection.cursor()
            for start in range(0, len(ids), _SQL_MAX_PARAMS):
                chunk = ids[start : start + _SQL_MAX_PARAMS]
                placeholders = ",".join("?" * len(chunk))
                cursor.execute(
                    f"SELECT DISTINCT source_guid FROM source_data "  # nosec B608  # only ? placeholders are interpolated
                    f"WHERE source_guid IN ({placeholders})",
                    chunk,
                )
                found.update(row["source_guid"] for row in cursor.fetchall())
        return found

    def records_share_a_repeat_chain(self, record_ids: Iterable[str]) -> bool:
        """Whether any of record_ids is a repeat, or is repeated by another row."""
        ids = tuple(dict.fromkeys(record_ids))
        if not ids:
            return False
        # Each id is bound twice in each predicate below, so chunk at half the
        # param cap to stay under it.
        chunk_size = _SQL_MAX_PARAMS // 2
        with self._lock:
            cursor = self.connection.cursor()
            for start in range(0, len(ids), chunk_size):
                chunk = ids[start : start + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                cursor.execute(
                    f"SELECT 1 FROM source_data WHERE "  # nosec B608  # only ? placeholders are interpolated
                    f"(repeat_of_source_guid > '' AND source_guid IN ({placeholders})) "
                    f"OR repeat_of_source_guid IN ({placeholders}) LIMIT 1",
                    chunk + chunk,
                )
                if cursor.fetchone() is not None:
                    return True
                # A NULL column is a row written before it existed: ask its payload.
                cursor.execute(
                    f"SELECT 1 FROM source_data WHERE repeat_of_source_guid IS NULL "  # nosec B608  # only ? placeholders are interpolated
                    f"AND typeof(data) = 'text' AND json_valid(data) AND ("
                    f"(source_guid IN ({placeholders}) "
                    f"AND json_extract(data, '$.repeat_of_source_guid') IS NOT NULL) "
                    f"OR json_extract(data, '$.repeat_of_source_guid') IN ({placeholders})) "
                    f"LIMIT 1",
                    chunk + chunk,
                )
                if cursor.fetchone() is not None:
                    return True
            # A compressed row is read here, as is a text row SQLite's JSON functions
            # refuse (nested 1000 levels deep, or holding a NaN), rather than failing
            # the query for every row.
            cursor.execute(
                "SELECT source_guid, data FROM source_data WHERE repeat_of_source_guid IS NULL"
                " AND (typeof(data) <> 'text' OR NOT json_valid(data))"
            )
            unreadable_by_sqlite = cursor.fetchall()
        wanted = set(ids)
        for row in unreadable_by_sqlite:
            stored = self.decode_payload(
                row["data"], table="source_data", where=f"record '{row['source_guid']}'"
            )
            repeat_of = stored.get("repeat_of_source_guid") if isinstance(stored, dict) else None
            if repeat_of is not None and (row["source_guid"] in wanted or repeat_of in wanted):
                return True
        return False

    def clear_source_data(self) -> None:
        """Delete all rows from source_data table."""
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute("DELETE FROM source_data")
                deleted = cursor.rowcount
                self._forget_dictionary(cursor, self._SOURCE_SCOPE, self._SOURCE_DATA)
                self.connection.commit()
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
