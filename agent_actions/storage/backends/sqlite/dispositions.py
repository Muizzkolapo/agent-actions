"""``record_disposition`` tracking for the SQLite store."""

import json
import sqlite3
from collections.abc import Iterable
from typing import Any

from agent_actions.storage.backend import (
    NODE_LEVEL_RECORD_ID,
    VALID_DISPOSITIONS,
    Disposition,
    DispositionRow,
)
from agent_actions.storage.backends.sqlite.codec import SQLitePayloadCodecMixin
from agent_actions.storage.backends.sqlite.common import _SQL_MAX_PARAMS, logger


class SQLiteDispositionMixin(SQLitePayloadCodecMixin):
    """Reads and writes the ``record_disposition`` table."""

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
                # UNIQUE is on (action_name, record_id, disposition), so DELETE first to prevent
                # coexistence.
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
                        self._compress_snapshot(cursor, action_name, input_snapshot),
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
                    [
                        (a, r, d, reason, rp, self._compress_snapshot(cursor, a, snap), detail)
                        for a, r, d, reason, rp, snap, detail in rows
                    ],
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
        *,
        snapshots: bool = True,
    ) -> list[dict[str, Any]]:
        """Query disposition records with optional filters.

        With ``snapshots`` False the rows carry no ``input_snapshot`` key and nothing is
        decoded: a run path that reads only ids and dispositions must not fail on a
        forensic column it never uses.
        """
        action_name = self._validate_identifier(action_name, "action_name")

        columns = "action_name, record_id, disposition, reason, relative_path, detail, created_at"
        if snapshots:
            columns += ", input_snapshot"
        query = f"SELECT {columns} FROM record_disposition WHERE action_name = ?"  # nosec B608  # columns are fixed literals
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
            found = [dict(row) for row in cursor.fetchall()]
        if snapshots:
            for row in found:
                row["input_snapshot"] = self.payload_text(
                    row["input_snapshot"],
                    table="record_disposition",
                    where=f"action '{row['action_name']}' record '{row['record_id']}'",
                )
        return found

    def actions_with_dispositions(self) -> list[str]:
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT DISTINCT action_name FROM record_disposition ORDER BY action_name"
            )
            return [row["action_name"] for row in cursor.fetchall()]

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
            f"SELECT DISTINCT record_id FROM record_disposition "  # nosec B608  # only ? placeholders are interpolated
            f"WHERE action_name = ? AND disposition IN ({placeholders}) "
            f"AND record_id != ?"
        )
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                sql,
                (action_name, *terminal, NODE_LEVEL_RECORD_ID),
            )
            return {row["record_id"] for row in cursor.fetchall()}

    def clear_dispositions_batch(self, action_name: str, record_ids: Iterable[str]) -> int:
        """Delete every disposition *action_name* holds under any of *record_ids*, at once.

        Returns count deleted. One transaction: no partial clear on failure.
        """
        action_name = self._validate_identifier(action_name, "action_name")
        ids = [
            self._validate_identifier(record_id, "record_id")
            for record_id in dict.fromkeys(record_ids)
        ]
        if not ids:
            return 0
        with self._lock:
            cursor = self.connection.cursor()
            try:
                deleted = 0
                for start in range(0, len(ids), _SQL_MAX_PARAMS):
                    chunk = ids[start : start + _SQL_MAX_PARAMS]
                    placeholders = ",".join("?" * len(chunk))
                    cursor.execute(
                        f"DELETE FROM record_disposition WHERE action_name = ? "  # nosec B608  # only ? placeholders are interpolated
                        f"AND record_id IN ({placeholders})",
                        (action_name, *chunk),
                    )
                    deleted += cursor.rowcount
                self.connection.commit()
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to batch clear dispositions: %s (count=%d)",
                    e,
                    len(ids),
                    extra={"action_name": action_name, "workflow_name": self.workflow_name},
                )
                raise
        logger.debug(
            "Batch cleared %d dispositions: action=%s",
            deleted,
            action_name,
            extra={"workflow_name": self.workflow_name},
        )
        return deleted

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
                deleted = cursor.rowcount
                if disposition is None and record_id is None:
                    self._forget_dictionary(cursor, action_name, self._SNAPSHOT)
                self.connection.commit()
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
