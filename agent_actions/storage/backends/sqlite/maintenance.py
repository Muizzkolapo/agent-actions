"""Statistics, post-run maintenance and the docs scan for the SQLite store."""

import sqlite3
from typing import Any

from agent_actions.config.defaults import StorageDefaults
from agent_actions.errors.processing import SerializationError
from agent_actions.storage.backend import (
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_SUCCESS,
)
from agent_actions.storage.backends.sqlite.codec import SQLitePayloadCodecMixin
from agent_actions.storage.backends.sqlite.common import logger


class SQLiteMaintenanceMixin(SQLitePayloadCodecMixin):
    """Store-wide statistics, WAL checkpoint, retention, VACUUM and scanning."""

    # VACUUM rewrites the whole file, so it waits until this share of it is freed pages.
    _VACUUM_FREE_FRACTION = 0.25

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
        prompt trace retention, source data TTL, and freed-page reclaim.

        All operations are idempotent and safe to run concurrently.
        """
        self._checkpoint_wal()
        self._cleanup_stale_dispositions()
        self._enforce_prompt_trace_retention(prompt_trace_retention_runs)
        if source_data_ttl_days is not None:
            self._enforce_source_data_ttl(source_data_ttl_days)
        self._reclaim_freed_pages()

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

    def _reclaim_freed_pages(self) -> None:
        """Give back the pages deleted rows left behind.

        A fresh run or a retry deletes most of a store, but SQLite keeps the
        freed pages inside the file, so it stays at its largest-ever size.
        VACUUM rewrites the file without them; in WAL mode the rewrite lands in
        the log first, so a checkpoint follows to move it into the file.
        """
        with self._lock:
            try:
                page_count = self.connection.execute("PRAGMA page_count").fetchone()[0]
                freelist_count = self.connection.execute("PRAGMA freelist_count").fetchone()[0]
                if page_count == 0 or freelist_count / page_count < self._VACUUM_FREE_FRACTION:
                    return
                self.connection.execute("VACUUM")
            except sqlite3.Error as e:
                logger.warning(
                    "Freed-page reclaim failed (non-fatal): %s",
                    e,
                    extra={"workflow_name": self.workflow_name},
                )
                return
        self._checkpoint_wal()
        logger.info(
            "Reclaimed %d of %d freed pages",
            freelist_count,
            page_count,
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
                    except (FileNotFoundError, SerializationError) as e:
                        logger.debug("Skipping %s/%s in scan: %s", action_name, rp, e)

                # Keyed on the prepare-time id: a durable guid would also match
                # rows from earlier runs and show a stale prompt as if current.
                # An expansion child's own id postdates its prompt.
                try:
                    candidates: set[str] = set()
                    for rec in records:
                        for tid in (rec.get("target_id"), rec.get("parent_target_id")):
                            if tid:
                                candidates.add(tid)
                    if candidates:
                        placeholders = ",".join("?" for _ in candidates)
                        cursor.execute(
                            f"SELECT record_id, compiled_prompt, llm_context, "  # nosec B608  # only ? placeholders are interpolated
                            f"response_text, model_name, model_vendor, run_mode, "
                            f"prompt_length, response_length, attempt "
                            f"FROM prompt_trace "
                            f"WHERE action_name = ? AND record_id IN ({placeholders})"
                            f" ORDER BY attempt DESC, id DESC",
                            [action_name, *candidates],
                        )
                        newest: dict[str, dict[str, Any]] = {}
                        for trace_row in cursor:
                            newest.setdefault(
                                trace_row["record_id"],
                                {
                                    "compiled_prompt": self.decompress_trace_text(
                                        trace_row["compiled_prompt"]
                                    ),
                                    "llm_context": self.decompress_trace_text(
                                        trace_row["llm_context"]
                                    ),
                                    "response_text": self.decompress_trace_text(
                                        trace_row["response_text"]
                                    ),
                                    "model_name": trace_row["model_name"],
                                    "model_vendor": trace_row["model_vendor"],
                                    "run_mode": trace_row["run_mode"],
                                    "prompt_length": trace_row["prompt_length"],
                                    "response_length": trace_row["response_length"],
                                    "attempt": trace_row["attempt"],
                                },
                            )
                        for rec in records:
                            trace_data = newest.get(rec.get("target_id") or "") or newest.get(
                                rec.get("parent_target_id") or ""
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
