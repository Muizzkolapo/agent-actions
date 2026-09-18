"""Resolution of the per-action record limit."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)

MAX_RECORDS_ENV = "AGAC_MAX_RECORDS"

# Stamped onto every action config when the run was asked for a cap.
MAX_RECORDS_KEY = "_max_records"

# Stamped with the source_guids a retry is re-running. A limit keeps the first N
# by position and would cut these loose; a retry cleared their dispositions
# before re-running, so cutting one erases the failure instead of repairing it.
RETRY_RECORD_IDS_KEY = "_retry_record_ids"


def _environment_ceiling() -> int | None:
    """Read the environment ceiling, refusing a value that cannot cap anything."""
    raw = os.environ.get(MAX_RECORDS_ENV)
    if raw is None:
        return None
    try:
        ceiling = int(raw)
    except ValueError:
        raise ValueError(f"{MAX_RECORDS_ENV}={raw!r} is not an integer") from None
    if ceiling < 1:
        raise ValueError(f"{MAX_RECORDS_ENV}={raw!r} must be at least 1")
    return ceiling


def _run_ceiling(action_config: Mapping[str, Any]) -> int | None:
    """Read the cap this run was asked for, refusing one that cannot cap anything."""
    ceiling = action_config.get(MAX_RECORDS_KEY)
    if ceiling is None:
        return None
    if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling < 1:
        raise ValueError(f"--max-records={ceiling!r} must be an integer of at least 1")
    return int(ceiling)


def _ceiling(action_config: Mapping[str, Any]) -> tuple[int | None, str]:
    """The ceiling in force and the name of what set it.

    A cap typed for this run outranks the environment variable by source, not by
    which number is smaller — otherwise ambient configuration could quietly
    overrule what was asked for.
    """
    # Read the variable whichever source wins: its guarantee is that an unusable
    # value fails the run, and being outranked is not the same as going unread.
    environment = _environment_ceiling()
    asked = _run_ceiling(action_config)
    if asked is not None:
        return asked, "--max-records"
    return environment, MAX_RECORDS_ENV


def records_kept_by_limit(
    records: Sequence[Any], limit: int, action_config: Mapping[str, Any]
) -> list[int]:
    """Indices of the first `limit` records, plus any this retry is re-running.

    A limit only ever admits more here, never fewer: it decides how much *new*
    work to take on, and a retried record is work already taken on. An identity
    is admitted once — source_guid is a content hash, so byte-identical rows
    share one, and admitting each position would store the record twice.
    """
    limit = max(limit, 0)
    kept = list(range(min(limit, len(records))))
    retried = action_config.get(RETRY_RECORD_IDS_KEY)
    # Only what retry stamped. A workflow's `default_agent_config` accepts
    # unknown keys and spreads them into every action, and YAML cannot express a
    # frozenset — so this is a handoff between commands, not a config surface.
    if not isinstance(retried, frozenset) or not retried:
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

    ceiling, source = _ceiling(action_config)
    if ceiling is None or (limit is not None and limit <= ceiling):
        return limit

    # A truncated run that says nothing looks like a complete one.
    logger.warning(
        "%s=%d caps this action at %d of %s configured records",
        source,
        ceiling,
        ceiling,
        limit if limit is not None else "unlimited",
    )
    return ceiling
