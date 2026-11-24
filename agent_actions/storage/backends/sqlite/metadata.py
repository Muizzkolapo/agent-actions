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

    def delete_metadata_prefix(self, prefix: str) -> int:
        """Delete all metadata keys that start with `prefix`. Returns count deleted.

        The match is exact and case-sensitive: no character of `prefix` is a wildcard.
        """
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "DELETE FROM workflow_metadata WHERE substr(key, 1, ?) = ?",
                (len(prefix), prefix),
            )
            self.connection.commit()
            return cursor.rowcount

    def list_metadata_prefix(self, prefix: str) -> list[str]:
        """Return all metadata keys that start with `prefix`, sorted lexically.

        The match is exact and case-sensitive: no character of `prefix` is a wildcard.
        """
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT key FROM workflow_metadata WHERE substr(key, 1, ?) = ? ORDER BY key",
                (len(prefix), prefix),
            )
            return [row["key"] for row in cursor.fetchall()]
