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
from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, Any

from agent_actions.record.state import RecordState

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


def stored_rows_not_reproduced(
    stored: Iterable[dict[str, Any]],
    produced: Iterable[dict[str, Any]],
    *,
    batch_inputs: Collection[str] = (),
) -> set[str]:
    """Identities in *stored* that *produced* did not write again.

    Matching is by input: two runs of a minting action share no identity, and how many
    rows an input yields is decided per run, so the same input mints several rows one
    run and keeps its own identity the next — each direction a replacement.

    Only a row settled as processed answers for an input, and what it answers for is
    the producers it names, else the identity it carries. Both halves need that test: a
    failed row is keyed on its input too, and a row can be stamped unsettled after
    enrichment named its producers.

    A stored row naming one input is inferred away; naming several, never. That reads
    one producer as a mint, which holds where this is called from — a batch row naming
    producers has been re-keyed — and not in general: the FILE writer records the inputs
    a row consumed *minus* its own, so a two-input merge keeps one identity and names
    one producer. Inferred away there, its own input's content goes with it, and a
    caller reading those rows wants the stricter reading ``build_carry_forward`` has.

    *batch_inputs* is the input before any narrowing, which settles what matching
    cannot: below an expansion the upstream children are minted again every run, so a
    producer named by no input is a generation that is gone rather than one this run did
    not answer for. Inferred only on a run that settled every input it recorded, since
    only then is the replacement in this write; left empty, or short of that, nothing is
    inferred at all. A row naming no producer is never inferred away either — its
    identity may be a gone generation's too, but an input that is merely absent is
    indistinguishable from one the run never took, and that one keeps its rows.
    """
    answered: set[str] = set()
    rewritten: set[str] = set()
    for row in produced:
        guid = row.get("source_guid")
        if guid:
            rewritten.add(guid)
        if row.get("_state") != RecordState.PROCESSED.value:
            continue
        # Producers are named during enrichment, before collection settles the state,
        # so an unsettled row can name an input it holds nothing for. Its own identity
        # is an input's only where it minted none of its own.
        if producers := (row.get("producer_source_guids") or ()):
            answered.update(producers)
        elif guid:
            answered.add(guid)

    inputs = frozenset(batch_inputs)
    stored_rows = list(stored)
    # Decided across all the mints at once, not per row: what replaces a generation is an
    # upstream action re-minting its whole output, so one producer missing while others are
    # still inputs is an individual record that went away, and its rows are its own.
    stored_mints = {
        producer
        for row in stored_rows
        if len(producer_set := frozenset(row.get("producer_source_guids") or ())) == 1
        for producer in producer_set
    }
    # ...and only on a run that settled every input it recorded: a run that failed, or
    # returned nothing, would read its own stored answers as replaced and delete them.
    generation_replaced = (
        bool(inputs)
        and bool(stored_mints)
        and inputs <= answered
        and stored_mints.isdisjoint(inputs)
    )

    carry: set[str] = set()
    dropped: set[str] = set()
    unattributable: set[str] = set()
    for row in stored_rows:
        guid = row.get("source_guid")
        if not guid:
            continue
        producers = frozenset(row.get("producer_source_guids") or ())
        # A row the run rewrote under this identity replaces it whatever else it says,
        # or the carried copy is appended beside that one and the identity is written
        # twice. A minted identity is never rewritten, so this decides nothing there.
        if guid in rewritten:
            continue
        superseded = False
        if len(producers) == 1:
            # On this path one producer means a mint, because a batch row that names any
            # is re-keyed. It does not mean that in general — see the docstring.
            reproduced = producers <= answered
            superseded = generation_replaced
        elif producers:
            # Several: the row holds what each input gave it, and its own identity is an
            # input's rather than a mint's. Never inferred away.
            reproduced = False
        else:
            # The identity is the input's own, so a run that did not take it simply
            # narrowed past it. Absence from the input is no evidence here.
            reproduced = guid in answered
        if not reproduced and not superseded:
            carry.add(guid)
            if not producers and batch_inputs and guid not in batch_inputs:
                # No producer to attribute it by, and no input of this run carries its
                # identity. Below an expansion that is the previous run's upstream child,
                # re-minted this run, so the row is carried beside its replacement and the
                # file grows every run. It is NOT safe to infer that here: an input that
                # is merely absent -- unstaged, filtered upstream, dropped by a limit --
                # looks identical, and its rows must be kept (#1151).
                unattributable.add(guid)
        elif not reproduced:
            dropped.add(guid)
    # An identity still carried through another of its rows has lost nothing.
    dropped -= carry

    if dropped:
        # INFO, not WARNING: a minting action below an expansion takes this path on
        # every healthy re-run, which is the case the inference exists for.
        logger.info(
            "%d stored row(s) dropped, not carried forward: the stored rows made from a "
            "single record name %d record(s) between them, none of which is among the %d "
            "input(s) this run recorded, and this run answered all of those inputs, so "
            "those rows are read as a generation the upstream action replaced. Expected "
            "on a re-run below an expansion, which mints its children again; if those "
            "records instead left this action's input, their rows are gone with them. "
            "See issue #1155",
            len(dropped),
            len(stored_mints),
            len(inputs),
        )

    if unattributable:
        logger.warning(
            "%d stored row(s) carry an identity no input of this run names and no "
            "producer to attribute them by, so they are kept beside the rows that "
            "replace them and this output grows every run. An action that answered an "
            "input with a single row records no producer, so below an expansion its "
            "rows name the previous run's upstream child; see issue #1155",
            len(unattributable),
        )
    return carry


def build_carry_forward(
    carry_ids: set[str],
    action_name: str,
    relative_path: str,
    storage_backend: StorageBackend,
    *,
    produced_by: Collection[str] = (),
    rewriting: Collection[str] = (),
) -> tuple[list[dict[str, Any]], set[str]]:
    """Read prior output for carry-forward records, returning (found, missing_ids).

    Reads the action's own prior output, so carried records keep its namespace. Missing
    ids must be re-queued by the caller, never dropped.

    *produced_by* names this run's INPUTS — the only ids resolvable through a row's
    ``producer_source_guids``, since ``carry_ids`` also holds stored-row ids where a
    repair named rows. *rewriting* names every identity this run writes a row under,
    wider than what it reprocesses; a row under one is reported as *missing* instead.
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
    inputs_carried = frozenset(produced_by) & carry_ids
    rows = [
        (index, rid, frozenset(record.get("producer_source_guids") or ()))
        for index, record in enumerate(prior_output)
        if (rid := record.get("source_guid"))
    ]
    rewritten = frozenset(rewriting)
    # A row naming a carried input and anything else — reprocessed, gone, or re-identified
    # — can be neither carried nor rebuilt. Read off every stored row, guid-less included.
    straddles = any(
        (producers := frozenset(record.get("producer_source_guids") or ()))
        and producers & inputs_carried
        and not producers <= inputs_carried
        for record in prior_output
    )

    chosen: dict[str, int] = {}
    produced_indices: set[int] = set()
    producers_found: set[str] = set()
    for index, rid, producers in rows:
        # Both routes refuse a row the run is writing under, or the carried copy lands
        # beside the run's own and the identity is stored twice (#1082). The rule is the
        # row's, not the route's: nothing reaches it here today, and something may.
        if rid in carry_ids and rid not in rewritten:
            chosen[rid] = index
        # An action minting an identity per row holds none carrying its input's, so the
        # rows it produced are the only place that input is named.
        if producers and not straddles and producers <= inputs_carried and rid not in rewritten:
            produced_indices.add(index)
            producers_found |= producers
    # Indices, so a row matched both ways is written once and keeps its place. Then one
    # row per identity: a producer can name two rows sharing a guid, and both would
    # write a duplicate.
    last_for_guid: dict[str, int] = {}
    for index in sorted(set(chosen.values()) | produced_indices):
        last_for_guid[prior_output[index]["source_guid"]] = index
    found: list[dict[str, Any]] = [prior_output[index] for index in sorted(last_for_guid.values())]
    missing: set[str] = carry_ids - set(chosen) - producers_found
    if missing:
        logger.warning(
            "Action '%s': %d carry-forward records not found in prior output — will reprocess",
            action_name,
            len(missing),
        )

    return found, missing
