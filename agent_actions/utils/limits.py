"""Resolution of the per-action record limit."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

MAX_RECORDS_ENV = "AGAC_MAX_RECORDS"


def _ceiling() -> int | None:
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


def effective_record_limit(action_config: Mapping[str, Any]) -> int | None:
    """Return the record limit for an action, or None when it is unlimited.

    ``bool`` is rejected rather than treated as an int: ``record_limit: true``
    in YAML would otherwise silently cap a run at one record.
    """
    limit = action_config.get("record_limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        limit = None

    ceiling = _ceiling()
    if ceiling is None or (limit is not None and limit <= ceiling):
        return limit

    # A truncated run that says nothing looks like a complete one.
    logger.warning(
        "%s=%d caps this action at %d of %s configured records",
        MAX_RECORDS_ENV,
        ceiling,
        ceiling,
        limit if limit is not None else "unlimited",
    )
    return ceiling
