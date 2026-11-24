"""``workflow_metadata`` key/value access for the SQLite store."""

from agent_actions.storage.backends.sqlite.common import SQLiteHost


class SQLiteMetadataMixin(SQLiteHost):
    """Reads and writes the ``workflow_metadata`` table."""

    def _save_metadata_raw(self, key: str, value: str) -> None:
        """Store a metadata key-value pair. Latest value wins (INSERT OR REPLACE).

        A failed commit is rolled back, so a later commit on this connection cannot
        store the value after the caller was told the save failed.
        """
        with self._lock:
            try:
                self.connection.execute(
                    "INSERT OR REPLACE INTO workflow_metadata (key, value, updated_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (key, value),
                )
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def increment_metadata(self, key: str) -> int:
        """Add one to an integer metadata value (absent is 0); returns the new value.

        One statement, so two processes on one store cannot both read the old value.
        """
        with self._lock:
            try:
                row = self.connection.execute(
                    "INSERT INTO workflow_metadata (key, value, updated_at) "
                    "VALUES (?, '1', CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1, "
                    "updated_at = CURRENT_TIMESTAMP RETURNING value",
                    (key,),
                ).fetchone()
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise
        return int(row[0])

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
