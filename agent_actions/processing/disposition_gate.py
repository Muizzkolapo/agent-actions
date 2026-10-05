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
from collections import Counter
from collections.abc import Callable, Collection, Iterable
from collections.abc import Set as AbstractSet
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from agent_actions.record.state import RecordState
from agent_actions.storage.backend import DISPOSITION_SUCCESS

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)

CARRY_FORWARD_REASON = "disposition_gate:already_terminal"

_FAILURE_STATES = frozenset({RecordState.FAILED.value, RecordState.EXHAUSTED.value})

# The named records each action found in its input, and those of them in a file it then
# processed to the end, per run. Keyed by the run's backend, as utils/limits.py keys what
# each slice admitted: `agac retry` runs a workflow in the process that just finished one.
_FOUND_BY_REPAIR: WeakKeyDictionary[Any, dict[str, set[str]]] = WeakKeyDictionary()
_ANSWERED_BY_REPAIR: WeakKeyDictionary[Any, dict[str, set[str]]] = WeakKeyDictionary()


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


def positions_named_by_repair(
    records: Any,
    repairing: Collection[str],
    *,
    storage_backend: Any = None,
    action_name: str | None = None,
) -> list[int] | None:
    """Positions of the records a repair named, or None when nothing is being repaired.

    None rather than every position so a caller neither re-slices nor re-pairs the
    positionally-matched lists it holds when there is nothing to narrow.

    Positions rather than records because the callers hold more than one list per
    input — staged text beside staged records, pre-observe records beside scoped
    ones — and a repair has to take the same slice out of each. Lists that are not
    matched position-for-position are each asked separately.

    Given the run's backend and the action, notes what it found for ``found_by_repair``.
    """
    if not repairing or not isinstance(records, list):
        return None
    kept = [
        index
        for index, record in enumerate(records)
        if isinstance(record, dict) and record.get("source_guid") in repairing
    ]
    if storage_backend is not None and action_name:
        _note(_FOUND_BY_REPAIR, storage_backend, action_name, (records[i] for i in kept))
    return kept


def note_answered_by_repair(
    records: Any,
    repairing: Collection[str],
    *,
    storage_backend: Any,
    action_name: str,
) -> None:
    """Note the named records among *records* as answered: their file was processed to the end.

    Called once the file returns, not where it is narrowed: a file that raises is caught
    and the walk carries on, so a record found in it was cleared and never re-decided.
    """
    if storage_backend is None or not repairing or not isinstance(records, list):
        return
    named = (r for r in records if isinstance(r, dict) and r.get("source_guid") in repairing)
    _note(_ANSWERED_BY_REPAIR, storage_backend, action_name, named)


def found_by_repair(storage_backend: Any, action_name: str) -> frozenset[str]:
    """The named records *action_name* found in its input during the run on this backend."""
    return _noted(_FOUND_BY_REPAIR, storage_backend, action_name)


def answered_by_repair(storage_backend: Any, action_name: str) -> frozenset[str]:
    """The named records found in a file *action_name* processed to the end in this run.

    A record a repair names and does not answer is one it cleared and did not re-decide.
    """
    return _noted(_ANSWERED_BY_REPAIR, storage_backend, action_name)


def _note(
    registry: WeakKeyDictionary[Any, dict[str, set[str]]],
    storage_backend: Any,
    action_name: str,
    records: Iterable[dict[str, Any]],
) -> None:
    noted = registry.setdefault(storage_backend, {}).setdefault(action_name, set())
    noted.update(record["source_guid"] for record in records)


def _noted(
    registry: WeakKeyDictionary[Any, dict[str, set[str]]],
    storage_backend: Any,
    action_name: str,
) -> frozenset[str]:
    if storage_backend is None:
        return frozenset()
    return frozenset(registry.get(storage_backend, {}).get(action_name, ()))


def every_answer_vouched_for(stored: Iterable[dict[str, Any]], answered: AbstractSet[str]) -> bool:
    """Whether each answer in *stored* is one its action still calls answered.

    *answered* is the records the action holds ``success`` for. A row's disposition is
    written under its own identity or under the input it names as producer, so either
    vouches for it. A reset clears every disposition and leaves the stored rows for the
    re-run to replace, so after one no stored answer is vouched for.
    """
    return all(
        row.get("_state") != RecordState.PROCESSED.value
        or row.get("source_guid") in answered
        or not answered.isdisjoint(row.get("producer_source_guids") or ())
        for row in stored
    )


def _answered_records(storage_backend: StorageBackend, action_name: str) -> set[str]:
    """The records *action_name* holds ``success`` for."""
    return {
        row["record_id"]
        for row in storage_backend.get_disposition(action_name, disposition=DISPOSITION_SUCCESS)
    }


def stored_answers_stand(
    storage_backend: StorageBackend, action_name: str, relative_path: str
) -> bool:
    """Whether a run of *relative_path* that failed and answered nothing leaves it as stored.

    It does while the action still calls every answer stored there answered: they stand
    over a run that produced only failures. After a reset it calls none of them answered,
    and left in place they would be served as answers to the config the reset replaced,
    so the run writes the file as one that answered something would. True when nothing
    is stored for it.
    """
    try:
        stored = storage_backend.read_target_for_rewrite(action_name, relative_path)
    except FileNotFoundError:
        return True
    return every_answer_vouched_for(stored, _answered_records(storage_backend, action_name))


def stored_rows_not_reproduced(
    stored: Iterable[dict[str, Any]],
    produced: Iterable[dict[str, Any]],
    *,
    batch_inputs: Collection[str] = (),
    filtered: Collection[str] = (),
    still_answered: Callable[[], AbstractSet[str]] | None = None,
) -> set[str]:
    """Identities in *stored* to write beside, or in place of, what *produced* holds.

    A stored row is carried where the input it answered for is one of *batch_inputs* and
    this run did not answer it; otherwise it is no part of this run's output, as online
    leaves it. An input in *filtered*, which this run's guard filtered, holds no row, as
    online writes none for it. Matching is by input, since a minting action's runs share
    no identity: a processed row answers for the producer it names, else for the identity
    it carries. With no inputs recorded every other unanswered row is carried. Where
    something failed and nothing was answered online leaves the stored file as it is, so
    every stored answer stands, over a row produced under its identity too, and a filtered
    input keeps what it held -- unless a stored answer is one the action no longer calls
    answered (``stored_answers_stand``). *still_answered* gives the records it holds
    ``success`` for, and is asked only then; without it every stored answer counts as one.
    """
    stored = list(stored)
    answered: set[str] = set()
    rewritten: set[str] = set()
    failed = False
    for row in produced:
        guid = row.get("source_guid")
        if guid:
            rewritten.add(guid)
        failed = failed or row.get("_state") in _FAILURE_STATES
        if row.get("_state") != RecordState.PROCESSED.value:
            continue
        # Producers are named during enrichment, before collection settles the state,
        # so an unsettled row can name an input it holds nothing for. Its own identity
        # is an input's only where it minted none of its own.
        if producers := (row.get("producer_source_guids") or ()):
            answered.update(producers)
        elif guid:
            answered.add(guid)

    refused = (
        failed
        and not answered
        and (still_answered is None or every_answer_vouched_for(stored, still_answered()))
    )
    inputs = frozenset(batch_inputs)
    excluded = frozenset(filtered)
    carry: set[str] = set()
    left: set[str] = set()
    filtered_out: set[str] = set()
    for row in stored:
        guid = row.get("source_guid")
        if not guid:
            continue
        stands = refused and row.get("_state") == RecordState.PROCESSED.value
        # A row the run rewrote under this identity replaces it whatever else it says,
        # or the carried copy is appended beside that one and the identity is written
        # twice.
        if guid in rewritten and not stands:
            continue
        producers = frozenset(row.get("producer_source_guids") or ())
        if len(producers) > 1:
            # Holds what each of several inputs gave it, so no one input accounts for it.
            carry.add(guid)
            continue
        answers_for = next(iter(producers), guid)
        if answers_for in answered:
            continue
        if answers_for in excluded and not refused:
            filtered_out.add(guid)
        elif inputs and answers_for not in inputs and not stands:
            left.add(guid)
        else:
            carry.add(guid)
    # An identity still carried through another of its rows has lost nothing.
    left -= carry
    filtered_out -= carry

    if left:
        logger.info(
            "%d stored row(s) not carried forward: the inputs they answered for are not "
            "among the %d this run took, so they are not part of this run's output. An "
            "input that returns is answered again.",
            len(left),
            len(inputs),
        )
    if filtered_out:
        logger.info(
            "%d stored row(s) not carried forward: the inputs they answered for are among "
            "the %d this run's guard filtered, and a filtered input holds no row.",
            len(filtered_out),
            len(excluded),
        )
    return carry


def with_stored_rows_not_reproduced(
    produced: list[dict[str, Any]],
    action_name: str,
    relative_path: str,
    storage_backend: StorageBackend,
    *,
    batch_inputs: Collection[str] = (),
    filtered: Collection[str] = (),
) -> list[dict[str, Any]]:
    """*produced* followed by every stored row it does not replace: the file to write.

    *relative_path* is the file being written and the only file read: the rows go
    straight to the write, so gathering them across the action's other files puts those
    files' records into this one. A store this cannot read raises rather than returning
    *produced* alone, which would replace the file.
    """
    try:
        stored = storage_backend.read_target_for_rewrite(action_name, relative_path)
    except FileNotFoundError:
        # Nothing stored for this file yet, so nothing to carry.
        return produced

    carry_guids = stored_rows_not_reproduced(
        stored,
        produced,
        batch_inputs=batch_inputs,
        filtered=filtered,
        still_answered=lambda: _answered_records(storage_backend, action_name),
    )
    if not carry_guids:
        return produced

    # Re-reads the same file, which the reconstruction cache answers, to keep the
    # one-row-per-identity rule in the place that owns it. Its checkpoint fallback is
    # unreachable: a file with no stored rows has returned above.
    carry_records, _missing = build_carry_forward(
        carry_guids, action_name, relative_path, storage_backend
    )
    if carry_records:
        logger.info(
            "Merging %d carry-forward records into batch output for %s",
            len(carry_records),
            action_name,
        )

    # A carried row replaces what the run produced under its identity: a stored answer
    # standing over the row of a run that failed and answered nothing.
    carried = {row["source_guid"] for row in carry_records}
    kept = [row for row in produced if row.get("source_guid") not in carried]

    # No `_delta_mode` stamp: `read_target_for_rewrite` marks the rows stored whole, so
    # a row round-trips into the mode it had. Stamping "full" would re-store every
    # carried row whole, rewriting rows this run never reprocessed.
    return kept + carry_records


def answered_since_stored(
    storage_backend: StorageBackend, action_name: str, relative_path: str
) -> set[str]:
    """Records of *relative_path* answered after its stored file was last written.

    Writing a file clears its checkpoint rows, so one beside a stored file is a later
    answer than the row stored for that record: the run that gave it stopped before
    writing the file again, after an edit or an upstream change reset the action. Neither
    row is fit to carry. The stored one is not the answer the record's disposition
    describes, and the checkpoint one lacks what enrichment adds, lineage among it.
    """
    checkpointed = {
        guid
        for row in storage_backend.read_checkpoint_records(action_name, relative_path)
        if (guid := row.get("source_guid"))
    }
    if not checkpointed:
        return set()
    try:
        storage_backend.read_target_for_rewrite(action_name, relative_path)
    except FileNotFoundError:
        # Nothing stored to be older than them: the checkpoint rows are what is carried.
        return set()
    return checkpointed


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

    A record checkpointed with several rows is reported *missing* too: an expansion's rows
    share their input's identity until enrichment mints one for each, and a checkpoint row
    is saved before that. Carried, they would keep that one identity, of which the carry
    keeps a single row. So is a record an earlier version checkpointed: it kept the last row.
    """
    answered_again: set[str] = set()
    try:
        prior_output = storage_backend.read_target_for_rewrite(action_name, relative_path)
    except FileNotFoundError:
        # No final output yet — check for checkpointed records from an
        # interrupted run.
        prior_output = storage_backend.read_checkpoint_records(action_name, relative_path)
        if not prior_output:
            logger.warning(
                "Prior output missing for %s/%s — all %d carry-forward records will be reprocessed",
                action_name,
                relative_path,
                len(carry_ids),
            )
            return [], carry_ids
        rows_per_record = Counter(row.get("source_guid") for row in prior_output)
        answered_again = {guid for guid, count in rows_per_record.items() if guid and count > 1}
        answered_again.update(
            storage_backend.checkpointed_without_row_count(action_name, relative_path)
        )
        prior_output = [row for row in prior_output if row.get("source_guid") not in answered_again]
        logger.info(
            "Action '%s': using %d checkpointed records for carry-forward",
            action_name,
            len(prior_output),
        )
        if asked := answered_again & carry_ids:
            logger.info(
                "Action '%s': %d checkpointed record(s) will be answered again: answered with "
                "several rows, or checkpointed by an earlier version that kept only the last",
                action_name,
                len(asked),
            )

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
    if not_found := missing - answered_again:
        logger.warning(
            "Action '%s': %d carry-forward records not found in prior output — will reprocess",
            action_name,
            len(not_found),
        )

    return found, missing
