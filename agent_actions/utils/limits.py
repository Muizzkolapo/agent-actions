"""Resolution of the per-action record limit."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

MAX_RECORDS_ENV = "AGAC_MAX_RECORDS"

# Stamped onto every action config when the run was asked for a cap.
MAX_RECORDS_KEY = "_max_records"

# Stamped on the actions a retry is about to re-run. Every limit here counts
# records or files and cuts by position; a retry works on records chosen by id,
# so a cut would drop the ones it was given and erase the failure it cleared.
RETRY_NO_LIMITS_KEY = "_retry_no_limits"


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


def limits_declined(action_config: Mapping[str, Any]) -> bool:
    """Whether this run refuses every limit that cuts by position."""
    return bool(action_config.get(RETRY_NO_LIMITS_KEY))


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
