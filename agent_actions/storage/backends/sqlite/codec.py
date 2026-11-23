"""Compression dictionaries and payload decoding for the SQLite store."""

import sqlite3
import zlib
from typing import Any

from agent_actions.errors.processing import SerializationError
from agent_actions.storage.backends.sqlite.common import SQLiteHost
from agent_actions.utils import deep_json


class SQLitePayloadCodecMixin(SQLiteHost):
    """zlib payload columns, each against a per-(scope, column) dictionary."""

    _TRACE_TEXT_COLUMNS = ("compiled_prompt", "llm_context", "response_text")

    # A compressed column names its dictionary "<table>.<column>". A payload column's
    # dictionary belongs to the action whose rows it serves; source rows belong to no
    # action and share one under an empty scope.
    _TARGET_DATA = "target_data.data"
    _SOURCE_DATA = "source_data.data"
    _CHECKPOINT_DATA = "checkpoint_output.record_data"
    _SNAPSHOT = "record_disposition.input_snapshot"
    _SOURCE_SCOPE = ""
    _DICTIONARY_SIZE = 32768
    # A trace dictionary: keyed prompt_trace.<column>, or by the bare column name in a
    # store written before the keys were qualified.
    _TRACE_DICTIONARY_SQL = (
        "(column_name LIKE 'prompt_trace.%'"
        " OR column_name IN ('compiled_prompt', 'llm_context', 'response_text'))"
    )

    def _compress(self, cursor: sqlite3.Cursor, scope: str, key: str, text: str) -> bytes:
        """Compress against the dictionary for (*scope*, *key*), made from its first value.

        Stored as a 4-byte dictionary id followed by a zlib stream; id 0 means no dictionary.
        """
        raw = text.encode("utf-8")
        dictionary_id, dictionary = 0, b""
        if raw:
            cursor.execute(
                "INSERT OR IGNORE INTO prompt_trace_dictionary (action_name, column_name, data)"
                " VALUES (?, ?, ?)",
                (scope, key, raw[-self._DICTIONARY_SIZE :]),
            )
            # Not cached: a rolled-back write frees this id for reuse, so only committed
            # dictionaries, which readers load, may be cached.
            cursor.execute(
                "SELECT id, data FROM prompt_trace_dictionary"
                " WHERE action_name = ? AND column_name = ?",
                (scope, key),
            )
            dictionary_id, dictionary = cursor.fetchone()
        compressor = zlib.compressobj(6, zdict=dictionary) if dictionary else zlib.compressobj(6)
        return dictionary_id.to_bytes(4, "big") + compressor.compress(raw) + compressor.flush()

    def _compress_trace_text(
        self, cursor: sqlite3.Cursor, action_name: str, column: str, text: str | None
    ) -> bytes | None:
        if text is None:
            return None
        return self._compress(cursor, action_name, f"prompt_trace.{column}", text)

    def _compress_snapshot(
        self, cursor: sqlite3.Cursor, action_name: str, input_snapshot: str | None
    ) -> bytes | None:
        if input_snapshot is None:
            return None
        return self._compress(cursor, action_name, self._SNAPSHOT, input_snapshot)

    @staticmethod
    def _forget_dictionary(cursor: sqlite3.Cursor, scope: str, key: str) -> None:
        """Drop a dictionary once the last row it served is gone, so the next write makes a new one."""
        cursor.execute(
            "DELETE FROM prompt_trace_dictionary WHERE action_name = ? AND column_name = ?",
            (scope, key),
        )

    def _dictionary(self, dictionary_id: int) -> bytes:
        if dictionary_id == 0:
            return b""
        # Under the lock: readers decode after their own query released it, and parallel
        # actions share this connection, so an unlocked SELECT here races their cursors.
        with self._lock:
            if dictionary_id not in self._dictionaries:
                row = self.connection.execute(
                    "SELECT data FROM prompt_trace_dictionary WHERE id = ?", (dictionary_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(
                        f"the row names dictionary {dictionary_id}, which the store does not hold"
                    )
                self._dictionaries[dictionary_id] = row[0]
            return self._dictionaries[dictionary_id]

    def _inflate(self, value: bytes) -> str:
        dictionary = self._dictionary(int.from_bytes(value[:4], "big"))
        decompressor = zlib.decompressobj(zdict=dictionary) if dictionary else zlib.decompressobj()
        return (decompressor.decompress(value[4:]) + decompressor.flush()).decode("utf-8")

    def decompress_trace_text(self, value: Any) -> Any:
        """Return trace text as written; a TEXT value is a row stored before compression."""
        if not isinstance(value, bytes):
            return value
        try:
            return self._inflate(value)
        except (zlib.error, ValueError) as e:
            raise ValueError(f"Unreadable compressed trace text: {e}") from e

    def payload_text(self, value: Any, *, table: str, where: str) -> Any:
        """The text a payload column holds, whether stored compressed or as text.

        These columns feed resume and retry, where empty data would pass for an
        answer, so a value that cannot be read is an error naming its row.
        """
        if not isinstance(value, bytes):
            return value
        try:
            return self._inflate(value)
        except (zlib.error, ValueError) as e:
            raise SerializationError(
                f"{table} for {where} cannot be read: {e}",
                context={"table": table, "where": where},
            ) from e

    def decode_payload(self, value: Any, *, table: str, where: str) -> Any:
        """The JSON a payload column holds; see :meth:`payload_text` for what fails."""
        text = self.payload_text(value, table=table, where=where)
        try:
            return deep_json.loads(text)
        except ValueError as e:
            raise SerializationError(
                f"{table} for {where} cannot be read: {e}",
                context={"table": table, "where": where},
            ) from e

    def _decompress_trace_row(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        trace = dict(row)
        for column in self._TRACE_TEXT_COLUMNS:
            if column in trace:
                trace[column] = self.decompress_trace_text(trace[column])
        return trace
