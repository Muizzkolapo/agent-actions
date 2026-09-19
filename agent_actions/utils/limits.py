"""Resolution of the per-action record limit."""

from __future__ import annotations

import logging
import os
from collections.abc import Collection, Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)

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

    A limit bounds how much *new* work a run takes on. While a run is repairing
    records it may still drop one the action has never processed — that is new
    work, and a configured limit is entitled to hold it back. What it may not do
    is drop a record this action already has a row for: the action's stored
    output is replaced whole, so leaving that record out of processing deletes
    the row rather than saving the work of making it.

    The records being repaired are added to that set rather than read from it:
    a retry clears their dispositions before re-running, so at this point they
    look like records the action never processed, and reading alone would drop
    exactly the records the repair exists to rewrite.
    """
    limit, source = resolve_record_limit(action_config)
    if limit is None or not isinstance(records, list):
        return None
    already: Collection[str] = ()
    if retried:
        stored = records_this_action_has_output_for(storage_backend, action_name)
        already = stored | frozenset(retried)
    kept = records_kept_by_limit(records, limit, already)
    if len(kept) == len(records):
        return None
    _announce_truncation(source, limit, len(kept), len(records), action_name)
    return kept


def records_kept_by_limit(
    records: Sequence[Any], limit: int, also_keep: Collection[str] = ()
) -> list[int]:
    """Indices of the first `limit` records, plus any of `also_keep` beyond them.

    An identity is admitted once — source_guid is a content hash, so byte-identical
    rows share one, and admitting each position would store the record twice.
    """
    limit = max(limit, 0)
    kept = list(range(min(limit, len(records))))
    if not also_keep:
        return kept

    seen = {
        records[index].get("source_guid") for index in kept if isinstance(records[index], Mapping)
    }
    for index in range(limit, len(records)):
        record = records[index]
        if not isinstance(record, Mapping):
            continue
        guid = record.get("source_guid")
        if guid in also_keep and guid not in seen:
            kept.append(index)
            seen.add(guid)
    return kept


def records_this_action_has_output_for(storage_backend: Any, action_name: str) -> frozenset[str]:
    """Ids this action already holds a stored row for.

    Read from the output rather than from dispositions: a retry clears the
    dispositions of what it repairs, and an action reset for a changed config has
    its dispositions cleared wholesale, so in both of the cases this exists to
    serve the disposition table is already empty. The rows outlive both.

    Duck-typed rather than imported: the resolver has no business depending on a
    storage implementation, and both slice sites already hold a backend.
    """
    if storage_backend is None:
        return frozenset()
    stored: set[str] = set()
    for path in storage_backend.list_target_files(action_name) or []:
        for row in storage_backend.read_target(action_name, path) or []:
            if isinstance(row, Mapping):
                guid = row.get("source_guid")
                if guid:
                    stored.add(guid)
    return frozenset(stored)
