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
from collections.abc import Collection
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
        repairing: Collection[str] = (),
    ) -> None:
        self._backend = storage_backend
        self._repairing = frozenset(repairing)
        self._terminal_ids_cache: dict[str, set[str]] = {}

    @property
    def repairing(self) -> frozenset[str]:
        """The records this run is repairing; empty when it is an ordinary run."""
        return self._repairing

    def carried_past_repair(self, action_name: str, relative_path: str | None) -> set[str]:
        """Identities this action holds a row for that the repair did not name.

        A repair processes only the records it named; the action's output is replaced
        whole, so every other row it holds has to be handed back to the write or
        narrowing the input would delete it.
        """
        if not self._repairing:
            return set()
        if not relative_path or self._backend is None:
            logger.warning(
                "Repairing '%s' without a stored path for its output: rows held for "
                "records the repair did not name cannot be carried and will be lost",
                action_name,
            )
            return set()
        return self._stored_guids(action_name, relative_path) - self._repairing

    def _stored_guids(self, action_name: str, relative_path: str) -> set[str]:
        """Identities this action already holds a row for in *relative_path*."""
        if self._backend is None:
            return set()
        try:
            prior = self._backend.read_target_for_rewrite(action_name, relative_path)
        except FileNotFoundError:
            return set()
        return {r["source_guid"] for r in prior if r.get("source_guid")}

    def filter(
        self,
        records: list[dict[str, Any]],
        action_name: str,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Partition records into (to_process, carry_ids).

        Returns:
            to_process: records with no terminal disposition.
            carry_ids: source_guids with terminal dispositions.
        """
        if self._backend is None:
            return records, set()

        if action_name not in self._terminal_ids_cache:
            self._terminal_ids_cache[action_name] = self._backend.get_terminal_record_ids(
                action_name
            )

        terminal_ids = self._terminal_ids_cache[action_name]
        if not terminal_ids:
            return records, set()

        to_process: list[dict[str, Any]] = []
        carry_ids: set[str] = set()
        for record in records:
            rid = record.get("source_guid")
            if rid is None or rid not in terminal_ids:
                to_process.append(record)
            else:
                carry_ids.add(rid)

        if carry_ids:
            logger.info(
                "Action '%s': %d record(s) carried forward, %d to process",
                action_name,
                len(carry_ids),
                len(to_process),
            )

        return to_process, carry_ids


def positions_named_by_repair(records: Any, repairing: Collection[str]) -> list[int] | None:
    """Positions of the records a repair named, or None when nothing is being repaired.

    None rather than every position so a caller neither re-slices nor re-pairs the
    positionally-matched lists it holds when there is nothing to narrow.

    Positions rather than records because the callers hold more than one list per
    input — staged text beside staged records, pre-observe records beside scoped
    ones — and a repair has to take the same slice out of each. Lists that are not
    matched position-for-position are each asked separately.
    """
    if not repairing or not isinstance(records, list):
        return None
    return [
        index
        for index, record in enumerate(records)
        if isinstance(record, dict) and record.get("source_guid") in repairing
    ]


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
        prior_output = storage_backend.read_target_for_rewrite(action_name, relative_path)
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

    # Walked in stored order rather than over `carry_ids`, which is a set: these
    # rows are written straight back into the file they came from, so iterating the
    # set would reshuffle rows nobody asked this run to touch.
    #
    # Still one row per identity, and still the last of them: several stored rows can
    # share a source_guid, and the mapping this replaced kept whichever came last.
    # Which of them ought to survive a rewrite is 615's question, not this one, so the
    # answer is left exactly where it was.
    chosen: dict[str, int] = {}
    for index, record in enumerate(prior_output):
        rid = record.get("source_guid")
        if rid in carry_ids:
            chosen[rid] = index
    found: list[dict[str, Any]] = [prior_output[index] for index in sorted(chosen.values())]
    missing: set[str] = carry_ids - set(chosen)
    if missing:
        logger.warning(
            "Action '%s': %d carry-forward records not found in prior output — will reprocess",
            action_name,
            len(missing),
        )

    return found, missing
