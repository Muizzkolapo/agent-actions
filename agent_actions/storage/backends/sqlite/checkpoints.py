"""``checkpoint_output`` rows for incremental online processing."""

import sqlite3
from collections.abc import Collection
from typing import Any

from agent_actions.errors.validation import DataValidationError
from agent_actions.storage.backends.sqlite.codec import SQLitePayloadCodecMixin
from agent_actions.storage.backends.sqlite.common import logger
from agent_actions.utils import deep_json


class SQLiteCheckpointMixin(SQLitePayloadCodecMixin):
    """Reads and writes the ``checkpoint_output`` table."""

    # ------------------------------------------------------------------
    # Checkpoint output (incremental online processing)
    # ------------------------------------------------------------------

    def save_checkpoint_records(
        self,
        action_name: str,
        relative_path: str,
        records: list[dict[str, Any]],
    ) -> None:
        """Store each record's rows as its answer, replacing any answer it held.

        One table row per ``source_guid``, holding every row given under it: an expansion's
        rows share their input's ``source_guid`` until enrichment mints one for each.
        """
        if not records:
            return
        action_name = self._validate_identifier(action_name, "action_name")
        relative_path = self._validate_identifier(relative_path, "relative_path")

        # Refuse to checkpoint a namespace that is the compiled JSON Schema instead of
        # LLM output — same seam guard write_target uses on target data.
        records = self._gate_schema_echo_records(action_name, records)

        # Fail loud on blank source_guid: UNIQUE + INSERT OR REPLACE would silently overwrite.
        answers: dict[str, list[dict[str, Any]]] = {}
        for index, r in enumerate(records):
            source_guid = r.get("source_guid")
            if not source_guid:
                raise DataValidationError(
                    f"Checkpoint record {index} for '{action_name}/{relative_path}' "
                    f"has no source_guid; refusing to drop it silently",
                    context={
                        "action_name": action_name,
                        "relative_path": relative_path,
                        "record_index": index,
                    },
                )
            answers.setdefault(source_guid, []).append(r)
        rows = [
            (action_name, relative_path, source_guid, deep_json.dumps(answer, ensure_ascii=False))
            for source_guid, answer in answers.items()
        ]
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.executemany(
                    "INSERT OR REPLACE INTO checkpoint_output "
                    "(action_name, relative_path, source_guid, record_data) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (
                            action,
                            path,
                            guid,
                            self._compress(cursor, action_name, self._CHECKPOINT_DATA, text),
                        )
                        for action, path, guid, text in rows
                    ],
                )
                self.connection.commit()
                logger.debug(
                    "Checkpointed %d records for %s/%s",
                    len(records),
                    action_name,
                    relative_path,
                    extra={"workflow_name": self.workflow_name},
                )
            except sqlite3.Error as e:
                self.connection.rollback()
                logger.error(
                    "Failed to save checkpoint records: %s",
                    e,
                    extra={"workflow_name": self.workflow_name},
                )
                raise

    def read_checkpoint_records(
        self,
        action_name: str,
        relative_path: str,
    ) -> list[dict[str, Any]]:
        """Every row checkpointed for an action/path, in the order their records were saved."""
        action_name = self._validate_identifier(action_name, "action_name")
        relative_path = self._validate_identifier(relative_path, "relative_path")

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT source_guid, record_data FROM checkpoint_output "
                "WHERE action_name = ? AND relative_path = ? ORDER BY id",
                (action_name, relative_path),
            )
            rows: list[dict[str, Any]] = []
            for stored in cursor.fetchall():
                answer = self.decode_payload(
                    stored["record_data"],
                    table="checkpoint_output",
                    where=f"action '{action_name}' file '{relative_path}'"
                    f" record '{stored['source_guid']}'",
                )
                rows.extend(answer)
            return rows

    def clear_checkpoint_records(
        self,
        action_name: str,
        relative_path: str | None = None,
        *,
        source_guids: Collection[str] | None = None,
    ) -> None:
        """Delete checkpoint records for an action, scoped to one path or to some records."""
        action_name = self._validate_identifier(action_name, "action_name")

        query = "DELETE FROM checkpoint_output WHERE action_name = ?"
        params: list[str] = [action_name]
        if relative_path is not None:
            relative_path = self._validate_identifier(relative_path, "relative_path")
            query += " AND relative_path = ?"
            params.append(relative_path)
        if source_guids is not None:
            guids = sorted(source_guids)
            if not guids:
                return
            query += f" AND source_guid IN ({', '.join('?' * len(guids))})"
            params.extend(guids)

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            deleted = cursor.rowcount
            if relative_path is None and source_guids is None:
                self._forget_dictionary(cursor, action_name, self._CHECKPOINT_DATA)
            self.connection.commit()
            if deleted > 0:
                logger.debug(
                    "Cleared %d checkpoint records for %s",
                    deleted,
                    action_name,
                    extra={"workflow_name": self.workflow_name},
                )
