"""Per-record disposition gate for retry idempotency.

Partitions records into (to_process, carry_ids) based on existing terminal
dispositions in the storage backend. Records with terminal dispositions are
skipped by the strategy and carried forward from prior output instead.

The gate runs ABOVE the strategy layer — strategies never see already-done
records. This is the same architectural layer as :mod:`cascade_filter`.

Instantiate once per workflow run. The instance-level cache avoids repeated
SQL queries across files within the same action.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)

CARRY_FORWARD_REASON = "disposition_gate:already_terminal"


class DispositionGate:
    """Per-record idempotency gate. Instantiate once per workflow run.

    The instance-level cache ensures one SQL query per action (not per file).
    Do NOT use a module-level cache — ``retry.py`` calls ``workflow.run()``
    in the same process after clearing dispositions, and a module-level cache
    would retain stale data from the first run.
    """

    def __init__(
        self,
        storage_backend: StorageBackend | None = None,
        selected: frozenset[str] | None = None,
    ) -> None:
        self._backend = storage_backend
        self._selected = selected
        self._terminal_ids_cache: dict[str, set[str]] = {}
        self._attempted_ids_cache: dict[str, set[str]] = {}

    def _terminal_ids(self, action_name: str) -> set[str]:
        if self._backend is None:
            return set()
        if action_name not in self._terminal_ids_cache:
            self._terminal_ids_cache[action_name] = self._backend.get_terminal_record_ids(
                action_name
            )
        return self._terminal_ids_cache[action_name]

    def _attempted_ids(self, action_name: str) -> set[str]:
        """Records that have run at this action, whatever the outcome.

        Only consulted when the run named its records: the distinction that
        matters then is tried vs never tried, which a terminal disposition does
        not draw — `failed` and `deferred` are records that ran.
        """
        if self._backend is None:
            return set()
        if action_name not in self._attempted_ids_cache:
            rows = self._backend.get_disposition(action_name)
            self._attempted_ids_cache[action_name] = {
                rid for row in rows if (rid := row.get("record_id"))
            }
        return self._attempted_ids_cache[action_name]

    def filter(
        self,
        records: list[dict[str, Any]],
        action_name: str,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Partition records into (to_process, carry_ids).

        A run that named its records takes those and any other record that ran
        here without finishing. Records that finished are carried, and records
        that never ran are left alone.
        """
        terminal_ids = self._terminal_ids(action_name)
        if self._selected is None and not terminal_ids:
            return records, set()

        attempted = self._attempted_ids(action_name) if self._selected is not None else set()
        to_process: list[dict[str, Any]] = []
        carry_ids: set[str] = set()
        for record in records:
            rid = record.get("source_guid")
            if self._selected is not None and rid in self._selected:
                to_process.append(record)
            elif rid is not None and rid in terminal_ids:
                carry_ids.add(rid)
            elif self._selected is None or (rid is not None and rid in attempted):
                to_process.append(record)

        if carry_ids or self._selected is not None:
            logger.info(
                "Action '%s': %d record(s) carried forward, %d to process",
                action_name,
                len(carry_ids),
                len(to_process),
            )

        return to_process, carry_ids


def build_carry_forward(
    carry_ids: set[str],
    action_name: str,
    relative_path: str,
    storage_backend: StorageBackend,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Read prior output for carry-forward records.

    Reads the current action's prior output (not upstream input) so that
    carried records include the action's enriched namespace.

    Returns (found_records, missing_ids). Missing IDs must be added back
    to ``to_process`` by the caller — never silently dropped.
    """
    try:
        prior_output = storage_backend.read_target(action_name, relative_path)
    except FileNotFoundError:
        # No final output yet — check for checkpointed records from an
        # interrupted run.
        prior_output = storage_backend.read_checkpoint_records(action_name, relative_path)
        if prior_output:
            logger.info(
                "Action '%s': using %d checkpointed records for carry-forward",
                action_name,
                len(prior_output),
            )
        else:
            logger.warning(
                "Prior output missing for %s/%s — all %d carry-forward records will be reprocessed",
                action_name,
                relative_path,
                len(carry_ids),
            )
            return [], carry_ids

    prior_by_guid = {r["source_guid"]: r for r in prior_output if r.get("source_guid")}
    found: list[dict[str, Any]] = []
    missing: set[str] = set()
    for rid in carry_ids:
        if rid in prior_by_guid:
            found.append(prior_by_guid[rid])
        else:
            missing.add(rid)
    if missing:
        logger.warning(
            "Action '%s': %d carry-forward records not found in prior output — will reprocess",
            action_name,
            len(missing),
        )

    return found, missing
