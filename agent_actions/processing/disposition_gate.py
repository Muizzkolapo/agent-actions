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

    def carried_past_repair(
        self,
        action_name: str,
        relative_path: str | None,
        inputs: Collection[Any],
    ) -> set[str]:
        """Identities this action holds a row for that this run will not write again.

        The output is replaced whole, so a row not produced again must be handed
        back or narrowing the input deletes it. An action minting an identity per
        row holds none carrying any input's, so rows are resolved to their input
        through ``parent_source_guid`` — read as a producer only where it names one
        of *inputs* (the action's input before narrowing), since that field is the
        original pool ancestor once an input has itself been expanded (#1022).
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

        records = [record for record in inputs if isinstance(record, dict)]
        held = {record["source_guid"] for record in records if record.get("source_guid")}
        # An ancestor standing in the input beside its own descendant no longer
        # identifies one input: a row of the descendant names it too, and guessing
        # hands those rows to a repair of the ancestor for the rewrite to drop.
        ancestors = {
            record["parent_source_guid"]
            for record in records
            if record.get("parent_source_guid") in held
        }
        named = held & self._repairing
        resolvable = named - ancestors
        blocked = named - resolvable

        carried: set[str] = set()
        unresolved: set[str] = set()
        for row in self._stored_rows(action_name, relative_path):
            guid = row.get("source_guid")
            if not guid:
                continue
            producer = row.get("parent_source_guid")
            if guid in named or producer in resolvable:
                continue
            if producer in blocked or (guid not in held and producer not in held):
                unresolved.add(guid)
            carried.add(guid)

        if unresolved and named:
            logger.warning(
                "Action '%s': %d stored row(s) cannot be attributed to an input of "
                "this run, so repairing %d record(s) carries them as untouched and "
                "duplicates any it regenerates. Either an identity minted below "
                "another mint, or an input standing beside its own ancestor; "
                "see issue #1022",
                action_name,
                len(unresolved),
                len(named),
            )
        return carried

    def _stored_rows(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Rows this action already holds in *relative_path*."""
        if self._backend is None:
            return []
        try:
            return self._backend.read_target_for_rewrite(action_name, relative_path)
        except FileNotFoundError:
            return []

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
    produced_indices: set[int] = set()
    producers_found: set[str] = set()
    for index, record in enumerate(prior_output):
        rid = record.get("source_guid")
        if rid in carry_ids:
            chosen[rid] = index
        # An action minting an identity per row holds none carrying its input's, so
        # the rows it produced are the only place that input is named.
        produced_for = carry_ids.intersection(record.get("producer_source_guids") or ())
        if produced_for:
            produced_indices.add(index)
            producers_found |= produced_for
    # Indices, so a row carried both ways is written once and a producer's rows keep
    # their place in the file rather than being appended after the direct matches.
    indices = sorted(set(chosen.values()) | produced_indices)
    found: list[dict[str, Any]] = [prior_output[index] for index in indices]
    missing: set[str] = carry_ids - set(chosen) - producers_found
    if missing:
        logger.warning(
            "Action '%s': %d carry-forward records not found in prior output — will reprocess",
            action_name,
            len(missing),
        )

    return found, missing
