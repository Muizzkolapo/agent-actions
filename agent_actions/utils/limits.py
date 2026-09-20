"""Resolution of the per-action record and file limits."""

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

# What each slice admitted, keyed the same way and for the same reason: a run is
# separated from the next by the backend it was built. ``None`` means a chunk
# could not be counted, and once unknown an action stays unknown.
_SLICE_OBSERVED: WeakKeyDictionary[Any, dict[str, tuple[int, bool] | None]] = WeakKeyDictionary()

RECORD_LIMIT_ENV = "AGAC_RECORD_LIMIT"
FILE_LIMIT_ENV = "AGAC_FILE_LIMIT"

# Stamped onto every action config when the run was asked for a limit.
RECORD_LIMIT_KEY = "_record_limit"
FILE_LIMIT_KEY = "_file_limit"

# Renamed. Read only to reject it: a run that believes it is capped and is not
# spends against a provider with no limit at all.
_RETIRED_ENV = "AGAC_MAX_RECORDS"


def check_environment() -> None:
    """Refuse an environment the run cannot honour before it starts.

    Resolving refuses the same values, but the first resolve of a run can happen
    after an action's work is done — a batch resume never slices, and a file
    limit is not consulted until a file has been walked — and failing there
    leaves that action unstamped. Called once while the run is being assembled.
    """
    _refuse_retired_name()
    _from_environment(RECORD_LIMIT_ENV)
    _from_environment(FILE_LIMIT_ENV)


def _refuse_retired_name() -> None:
    if os.environ.get(_RETIRED_ENV) is not None:
        raise ValueError(f"{_RETIRED_ENV} is not read; set {RECORD_LIMIT_ENV} instead")


def _from_environment(name: str) -> int | None:
    """Read the limit *name* asks for, refusing one that cannot limit anything.

    An empty value reads as unset: ``AGAC_FILE_LIMIT= agac run`` is how a shell
    says the variable is not being used, and failing a run over it would refuse
    the spelling rather than the intent.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        limit = int(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not an integer") from None
    if limit < 1:
        raise ValueError(f"{name}={raw!r} must be at least 1")
    return limit


def _from_run(action_config: Mapping[str, Any], key: str, flag: str) -> int | None:
    """Read the limit this run was asked for, refusing one that cannot limit anything."""
    limit = action_config.get(key)
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"{flag}={limit!r} must be an integer of at least 1")
    return int(limit)


def _resolve(
    action_config: Mapping[str, Any], config_key: str, run_key: str, env: str, flag: str
) -> tuple[int | None, str]:
    """The limit in force for an action, and the name of what set it.

    Silent by design. Whether anything was actually held back depends on how much
    there is to hold back, which only the site applying the limit knows;
    announcing from here describes a truncation that may not happen.

    ``bool`` is rejected rather than treated as an int: ``record_limit: true``
    in YAML would otherwise silently cap a run at one record.
    """
    _refuse_retired_name()
    in_config = action_config.get(config_key)
    if isinstance(in_config, bool) or not isinstance(in_config, int) or in_config < 1:
        in_config = None

    # Read the variable whichever source wins: its guarantee is that an unusable
    # value fails the run, and being outranked is not the same as going unread.
    environment = _from_environment(env)
    asked = _from_run(action_config, run_key, flag)
    # A limit typed for this run outranks the environment by source, not by which
    # number is smaller — otherwise ambient configuration could quietly overrule
    # what was asked for.
    override, source = (asked, flag) if asked is not None else (environment, env)

    if override is None or (in_config is not None and in_config <= override):
        return in_config, config_key
    return override, source


def resolve_record_limit(action_config: Mapping[str, Any]) -> tuple[int | None, str]:
    """How many records of an input file an action may process, and what set it."""
    return _resolve(
        action_config, "record_limit", RECORD_LIMIT_KEY, RECORD_LIMIT_ENV, "--record-limit"
    )


def resolve_file_limit(action_config: Mapping[str, Any]) -> tuple[int | None, str]:
    """How many input files an action may walk, and what set it."""
    return _resolve(action_config, "file_limit", FILE_LIMIT_KEY, FILE_LIMIT_ENV, "--file-limit")


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


def _observe_slice(
    storage_backend: Any, action_name: str, *, processed: int, truncated: bool
) -> None:
    """Add what one slice admitted to the action's running total."""
    if storage_backend is None:
        return
    per_action = _SLICE_OBSERVED.setdefault(storage_backend, {})
    if action_name in per_action and per_action[action_name] is None:
        return
    seen, dropped = per_action.get(action_name) or (0, False)
    per_action[action_name] = (seen + processed, dropped or truncated)


def _forget_slice(storage_backend: Any, action_name: str) -> None:
    """Mark the action's count unknowable, permanently for this run.

    Leaving an uncountable chunk out of the sum would under-count instead, and
    an under-count is the one error that reads as "a smaller limit could not
    have bitten" — which skips an action that limit would in fact cut down.
    """
    if storage_backend is None:
        return
    _SLICE_OBSERVED.setdefault(storage_backend, {})[action_name] = None


def slice_observation(storage_backend: Any, action_name: str) -> tuple[int, bool] | None:
    """How many records the slices admitted for *action_name*, and whether any were dropped.

    ``None`` when nothing was observed — an action that never sliced, because it
    was skipped or resumed — or when a chunk could not be counted. Both read as
    unknown, which must keep the coarse behaviour rather than vouch for a limit.
    """
    if storage_backend is None:
        return None
    return _SLICE_OBSERVED.get(storage_backend, {}).get(action_name)


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

    Records what it admitted as it goes, for ``slice_observation``: this is the
    only place that knows both the count and whether anything was dropped, the
    same reason the announcement lives here.

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
    if not isinstance(records, list):
        _forget_slice(storage_backend, action_name)
        return None
    if limit is None:
        _observe_slice(storage_backend, action_name, processed=len(records), truncated=False)
        return None
    rows_held: dict[str, int] = {}
    if retried:
        rows_held = dict(rows_this_action_holds_per_record(storage_backend, action_name))
        for guid in retried:
            rows_held.setdefault(guid, 1)
    kept = records_kept_by_limit(records, limit, rows_held)
    _observe_slice(
        storage_backend, action_name, processed=len(kept), truncated=len(kept) < len(records)
    )
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

    Offers, not guarantees: what is finally written also passes through
    carry-forward, which rebuilds an action's output keyed by identity and so
    collapses several rows of one identity into a single row regardless of what is
    kept here. That collapse is a separate defect on a separate path; this decides
    only what the limit hands on.
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
