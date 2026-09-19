"""Resolution of the per-action record limit."""

from __future__ import annotations

import logging
import os
from collections.abc import Collection, Mapping, Sequence
from typing import Any
from weakref import WeakKeyDictionary

logger = logging.getLogger(__name__)

# Per-backend, per-action. Weak so it dies with the backend rather than outliving
# it: `agac retry` runs a workflow in the process that just finished one.
_STORED_ROWS: WeakKeyDictionary[Any, dict[str, dict[str, int]]] = WeakKeyDictionary()

RECORD_LIMIT_ENV = "AGAC_RECORD_LIMIT"

# Stamped onto every action config when the run was asked for a limit.
RECORD_LIMIT_KEY = "_record_limit"

# Renamed. Read only to reject it: a run that believes it is capped and is not
# spends against a provider with no limit at all.
_RETIRED_ENV = "AGAC_MAX_RECORDS"


def check_environment() -> None:
    """Refuse a retired variable name before a run starts.

    Resolving refuses it too, but the first resolve of a run can happen after an
    action's work is done — a batch resume never slices — and failing there
    leaves that action unstamped. Called once while the run is being assembled.
    """
    if os.environ.get(_RETIRED_ENV) is not None:
        raise ValueError(f"{_RETIRED_ENV} is no longer read — use {RECORD_LIMIT_ENV}")


def _from_environment() -> int | None:
    """Read the limit the environment asks for, refusing one that cannot limit anything."""
    check_environment()
    raw = os.environ.get(RECORD_LIMIT_ENV)
    if raw is None:
        return None
    try:
        limit = int(raw)
    except ValueError:
        raise ValueError(f"{RECORD_LIMIT_ENV}={raw!r} is not an integer") from None
    if limit < 1:
        raise ValueError(f"{RECORD_LIMIT_ENV}={raw!r} must be at least 1")
    return limit


def _from_run(action_config: Mapping[str, Any]) -> int | None:
    """Read the limit this run was asked for, refusing one that cannot limit anything."""
    limit = action_config.get(RECORD_LIMIT_KEY)
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"--record-limit={limit!r} must be an integer of at least 1")
    return int(limit)


def resolve_record_limit(action_config: Mapping[str, Any]) -> tuple[int | None, str]:
    """The record limit in force for an action, and the name of what set it.

    Silent by design. Whether anything was actually dropped depends on how many
    records there are, which only a slice site knows; announcing from here
    describes a truncation that may not happen.

    ``bool`` is rejected rather than treated as an int: ``record_limit: true``
    in YAML would otherwise silently cap a run at one record.
    """
    configured = action_config.get("record_limit")
    if isinstance(configured, bool) or not isinstance(configured, int) or configured < 1:
        configured = None

    # Read the variable whichever source wins: its guarantee is that an unusable
    # value fails the run, and being outranked is not the same as going unread.
    environment = _from_environment()
    asked = _from_run(action_config)
    # A limit typed for this run outranks the environment by source, not by which
    # number is smaller — otherwise ambient configuration could quietly overrule
    # what was asked for.
    override, source = (
        (asked, "--record-limit") if asked is not None else (environment, RECORD_LIMIT_ENV)
    )

    if override is None or (configured is not None and configured <= override):
        return configured, "record_limit"
    return override, source


def _announce_truncation(source: str, limit: int, kept: int, total: int, action_name: str) -> None:
    """Loudly when something outside the config dropped the records.

    A limit the workflow asks for is the run behaving as written; one asked for
    elsewhere may be a variable the caller has forgotten is set, and a truncated
    run that stays quiet looks like a complete one.
    """
    level = logging.INFO if source == "record_limit" else logging.WARNING
    logger.log(
        level,
        "%s=%d: processing %d of %d records for %s",
        source,
        limit,
        kept,
        total,
        action_name,
    )


def first_record_per_identity(
    records: list[dict[str, Any]], aligned: list[Any] | None = None
) -> tuple[list[dict[str, Any]], list[Any] | None]:
    """The first record carrying each ``source_guid``, and *aligned* kept in step.

    Mirrors what the store does to the same list when it is asked to deduplicate,
    which is how staging saves: source rows are unique on (path, guid) and are
    written INSERT OR IGNORE, so the first record of an identity is the one kept.
    Asked not to deduplicate the store writes INSERT OR REPLACE and the last wins
    instead — a configuration no caller uses, and one this would not match. A list that is processed after being saved has to
    agree with what was saved, or the action writes more output rows than it has
    records and every identity-keyed path afterwards — dispositions,
    carry-forward, retry — reads a different count than the output shows.

    A record with no ``source_guid`` is passed through rather than dropped or
    merged: identity is not ours to invent here, and the storage boundary already
    refuses such a record loudly.
    """
    seen: set[str] = set()
    kept_indices: list[int] = []
    for index, record in enumerate(records):
        guid = record.get("source_guid") if isinstance(record, dict) else None
        if guid:
            if guid in seen:
                continue
            seen.add(guid)
        kept_indices.append(index)

    if len(kept_indices) == len(records):
        return records, aligned

    deduped = [records[i] for i in kept_indices]
    if aligned is None or not isinstance(aligned, list):
        return deduped, aligned
    return deduped, [aligned[i] for i in kept_indices if i < len(aligned)]


def record_indices_to_process(
    records: Any,
    action_config: Mapping[str, Any],
    action_name: str,
    retried: Collection[str] = (),
    storage_backend: Any = None,
) -> list[int] | None:
    """Which indices of *records* the limit admits, or None when it admits all.

    None rather than every index, so a caller neither re-slices nor announces
    when nothing was dropped: what makes a truncation worth saying is that it
    happened, which needs the record count and so cannot be decided where the
    limit is resolved.

    Expects one record per identity already — :func:`first_record_per_identity`
    runs first at the staging site. A limit chooses *positions*, so reducing the
    list afterwards would spend the limit on positions that then collapse, and
    the count this announces would describe a list that no longer exists.

    A limit bounds how much *new* work a run takes on. While a run is repairing
    records it may still drop one the action has never processed — that is new
    work, and a configured limit is entitled to hold it back. What it may not do
    is drop a record this action already has a row for: the action's stored
    output is replaced whole, so leaving that record out of processing deletes
    the row rather than saving the work of making it.

    The records being repaired are added to that set rather than read from it: a
    record may have no row at all at this action — it failed before writing one,
    or the action never ran for it — and it is the one record the repair exists
    to rewrite, so reading alone would drop exactly that.
    """
    limit, source = resolve_record_limit(action_config)
    if limit is None or not isinstance(records, list):
        return None
    rows_held: dict[str, int] = {}
    if retried:
        rows_held = dict(rows_this_action_holds_per_record(storage_backend, action_name))
        for guid in retried:
            rows_held.setdefault(guid, 1)
    kept = records_kept_by_limit(records, limit, rows_held)
    if len(kept) == len(records):
        return None
    if retried and storage_backend is None:
        # Only the named records could be spared, which is the behaviour this
        # rule exists to replace. Said where records were actually dropped, so
        # it names a loss rather than a possibility.
        logger.warning(
            "No storage backend while repairing records: %s kept only the records named, "
            "and rows it already held have been dropped",
            action_name,
        )
    _announce_truncation(source, limit, len(kept), len(records), action_name)
    return kept


def records_kept_by_limit(
    records: Sequence[Any], limit: int, rows_held: Mapping[str, int] | None = None
) -> list[int]:
    """Indices of the first `limit` records, plus enough beyond it to cover `rows_held`.

    `rows_held` says how many rows the action already holds for each identity, and
    that many positions carrying it are kept — no more, no fewer. Fewer offers the
    write fewer rows than stood there; more offers it three where one did,
    backfilling past a limit that was deliberately holding records back. Positions
    the limit keeps by count spend from the same budget, since they cover those
    rows too.

    Several rows can share an identity at an action that expanded its input —
    file-mode tools reattach a parent's guid to each row they produce — so the
    count matters there. It cannot arise from staged records: those are reduced
    to one record per identity before this runs, because the source store keeps
    one row per identity and the two have to agree.
    """
    limit = max(limit, 0)
    kept = list(range(min(limit, len(records))))
    if not rows_held:
        return kept

    budget = dict(rows_held)
    for index in kept:
        record = records[index]
        if isinstance(record, Mapping):
            guid = record.get("source_guid")
            if guid in budget:
                budget[guid] -= 1

    for index in range(limit, len(records)):
        record = records[index]
        if not isinstance(record, Mapping):
            continue
        guid = record.get("source_guid")
        if guid is not None and budget.get(guid, 0) > 0:
            kept.append(index)
            budget[guid] -= 1
    return kept


def rows_this_action_holds_per_record(storage_backend: Any, action_name: str) -> dict[str, int]:
    """How many stored rows this action holds for each identity.

    Read from the output rather than from dispositions: a retry clears the
    dispositions of what it repairs, and an action reset for a changed config has
    its dispositions cleared wholesale, so in both of the cases this exists to
    serve the disposition table is already empty. The rows outlive both.

    Answered once per action per backend, because the caller asks per input file and
    reading the store each time is quadratic in files. Keyed weakly so an entry
    cannot outlive the backend it describes — object identity is what separates one
    run from the next here, since each is built its own backend, and a plain
    module-level dict would hold every backend alive besides.
    """
    if storage_backend is None:
        return {}
    per_action = _STORED_ROWS.setdefault(storage_backend, {})
    if action_name not in per_action:
        per_action[action_name] = storage_backend.target_rows_per_source_guid(action_name)
    return per_action[action_name]
