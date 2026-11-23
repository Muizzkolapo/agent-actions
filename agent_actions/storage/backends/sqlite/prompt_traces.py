"""``prompt_trace`` rows for the SQLite store."""

import json
import sqlite3
from typing import Any

from agent_actions.logging.diagnostics import DIAGNOSTIC
from agent_actions.storage.backends.sqlite.codec import SQLitePayloadCodecMixin
from agent_actions.storage.backends.sqlite.common import logger


class SQLitePromptTraceMixin(SQLitePayloadCodecMixin):
    """Reads and writes the ``prompt_trace`` table."""

    _MAX_TRACE_FIELD_SIZE = 1_048_576  # 1MB

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
                extra=DIAGNOSTIC,
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
        answered_under: str | None = None,
    ) -> None:
        """Persist the compiled prompt and LLM context for a single record.

        ``record_id`` is the prepare-time target_id; ``source_guid`` is the
        durable identity that joins key on. The latter is not identifier-
        validated: a first-stage row may carry its own, so rejecting one would
        drop a record from processing over a telemetry write. It is a bound
        parameter, never interpolated, so nothing is gained by checking it.
        """
        action_name = self._validate_identifier(action_name, "action_name")
        record_id = self._validate_identifier(record_id, "record_id")

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
                stored_prompt, stored_context, stored_response = (
                    self._compress_trace_text(cursor, action_name, column, text)
                    for column, text in zip(
                        self._TRACE_TEXT_COLUMNS,
                        (compiled_prompt, llm_context, response_text),
                        strict=True,
                    )
                )
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO prompt_trace
                    (action_name, record_id, source_guid, run_id, attempt,
                     compiled_prompt, llm_context,
                     response_text, model_name, model_vendor, run_mode,
                     prompt_length, context_length, response_length, answered_under,
                     created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        action_name,
                        record_id,
                        source_guid,
                        run_id,
                        attempt,
                        stored_prompt,
                        stored_context,
                        stored_response,
                        model_name,
                        model_vendor,
                        run_mode,
                        prompt_length,
                        context_length,
                        response_length,
                        answered_under,
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
        record_id: str,
        response_text: str,
        parent_record_id: str | None = None,
        attempt: int | None = None,
    ) -> None:
        """Attach the LLM response to the newest trace row for a prepared task.

        With ``attempt``, to that attempt's row: a repair loop can ship an earlier
        attempt's response, which belongs beside the prompt that drew it.

        Keyed on the prepare-time id, not the durable guid: only a per-run id
        can answer "which prompt produced this on this run" without reaching a
        previous run's rows. An expansion child's own id postdates its prompt,
        so it falls back to ``parent_record_id``. A miss is logged — a response
        with no row to land on is trace loss.
        """
        action_name = self._validate_identifier(action_name, "action_name")
        record_id = self._validate_identifier(record_id, "record_id")
        if parent_record_id:
            parent_record_id = self._validate_identifier(parent_record_id, "parent_record_id")

        response_length = len(response_text) if response_text else 0
        response_text = self._cap_trace_field(response_text) or ""

        with self._lock:
            cursor = self.connection.cursor()
            try:
                stored_response = self._compress_trace_text(
                    cursor, action_name, "response_text", response_text
                )
                cursor.execute(
                    """
                    UPDATE prompt_trace
                    SET response_text = ?, response_length = ?
                    WHERE id = (
                        SELECT id FROM prompt_trace
                        WHERE action_name = ? AND record_id IN (?, ?)
                          AND (? IS NULL OR attempt = ?)
                        ORDER BY (record_id = ?) DESC, attempt DESC, id DESC LIMIT 1
                    )
                    """,
                    (
                        stored_response,
                        response_length,
                        action_name,
                        record_id,
                        parent_record_id or record_id,
                        attempt,
                        attempt,
                        record_id,
                    ),
                )
                self.connection.commit()
                if cursor.rowcount > 0:
                    logger.debug(
                        "Updated prompt trace response: action=%s record=%s",
                        action_name,
                        record_id,
                        extra={"workflow_name": self.workflow_name},
                    )
                else:
                    logger.warning(
                        "No prompt trace row for action=%s record=%s — response not recorded",
                        action_name,
                        record_id,
                        extra={**DIAGNOSTIC, "workflow_name": self.workflow_name},
                    )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.warning(
                    "Failed to update prompt trace response: %s",
                    e,
                    extra={
                        "action_name": action_name,
                        "record_id": record_id,
                        "workflow_name": self.workflow_name,
                    },
                )

    _TRACE_SELECT_LIST = ", ".join(
        (
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
            "answered_under",
            "created_at",
        )
    )

    def get_prompt_traces(
        self,
        action_name: str,
        record_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve prompt traces for an action, optionally filtered by record."""
        action_name = self._validate_identifier(action_name, "action_name")

        query = f"SELECT {self._TRACE_SELECT_LIST} FROM prompt_trace WHERE action_name = ?"  # nosec B608  # the fixed _TRACE_SELECT_LIST
        params: list[Any] = [action_name]

        if record_id is not None:
            record_id = self._validate_identifier(record_id, "record_id")
            query += " AND record_id = ?"
            params.append(record_id)

        query += " ORDER BY id"

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            return [self._decompress_trace_row(row) for row in cursor.fetchall()]

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
            compiled_prompt = self.decompress_trace_text(row["compiled_prompt"])

        return {
            "action_name": action_name,
            "compiled_prompt": compiled_prompt,
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
                f"SELECT {self._TRACE_SELECT_LIST} FROM prompt_trace"  # nosec B608  # the fixed _TRACE_SELECT_LIST
                " WHERE action_name = ? ORDER BY id LIMIT ? OFFSET ?",
                (action_name, limit, offset),
            )
            records = [self._decompress_trace_row(row) for row in cursor.fetchall()]

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
                    deleted = cursor.rowcount
                    cursor.execute(
                        "DELETE FROM prompt_trace_dictionary WHERE action_name = ? AND "  # nosec B608  # appends the constant _TRACE_DICTIONARY_SQL
                        + self._TRACE_DICTIONARY_SQL,
                        (action_name,),
                    )
                else:
                    cursor.execute("DELETE FROM prompt_trace")
                    deleted = cursor.rowcount
                    cursor.execute(
                        "DELETE FROM prompt_trace_dictionary WHERE " + self._TRACE_DICTIONARY_SQL  # nosec B608  # appends the constant _TRACE_DICTIONARY_SQL
                    )
                self.connection.commit()
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
