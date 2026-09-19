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


def _from_environment() -> int | None:
    """Read the limit the environment asks for, refusing one that cannot limit anything."""
    if os.environ.get(_RETIRED_ENV) is not None:
        raise ValueError(f"{_RETIRED_ENV} is no longer read — use {RECORD_LIMIT_ENV}")
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


def _override(action_config: Mapping[str, Any]) -> tuple[int | None, str]:
    """The limit asked for outside the workflow config, and the name of what asked.

    A limit typed for this run outranks the environment variable by source, not by
    which number is smaller — otherwise ambient configuration could quietly
    overrule what was asked for.
    """
    # Read the variable whichever source wins: its guarantee is that an unusable
    # value fails the run, and being outranked is not the same as going unread.
    environment = _from_environment()
    asked = _from_run(action_config)
    if asked is not None:
        return asked, "--record-limit"
    return environment, RECORD_LIMIT_ENV


def records_kept_by_limit(
    records: Sequence[Any], limit: int, retried: Collection[str] = ()
) -> list[int]:
    """Indices of the first `limit` records, plus any of `retried` beyond them.

    A limit only ever admits more here, never fewer: it decides how much *new*
    work to take on, and a record being repaired is work already taken on. An
    identity is admitted once — source_guid is a content hash, so byte-identical
    rows share one, and admitting each position would store the record twice.
    """
    limit = max(limit, 0)
    kept = list(range(min(limit, len(records))))
    if not retried:
        return kept

    seen = {
        records[index].get("source_guid") for index in kept if isinstance(records[index], Mapping)
    }
    for index in range(limit, len(records)):
        record = records[index]
        if not isinstance(record, Mapping):
            continue
        guid = record.get("source_guid")
        if guid in retried and guid not in seen:
            kept.append(index)
            seen.add(guid)
    return kept


def effective_record_limit(action_config: Mapping[str, Any]) -> int | None:
    """Return the record limit for an action, or None when it is unlimited.

    ``bool`` is rejected rather than treated as an int: ``record_limit: true``
    in YAML would otherwise silently cap a run at one record.
    """
    limit = action_config.get("record_limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        limit = None

    override, source = _override(action_config)
    if override is None or (limit is not None and limit <= override):
        return limit

    # A truncated run that says nothing looks like a complete one.
    logger.warning(
        "%s=%d caps this action at %d of %s configured records",
        source,
        override,
        override,
        limit if limit is not None else "unlimited",
    )
    return override
