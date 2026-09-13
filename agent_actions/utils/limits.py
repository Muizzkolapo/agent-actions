"""Resolution of the per-action record limit."""

from __future__ import annotations

from typing import Any


def effective_record_limit(action_config: dict[str, Any]) -> int | None:
    """Return the record limit for an action, or None when it is unlimited.

    ``bool`` is rejected rather than treated as an int: ``record_limit: true``
    in YAML would otherwise silently cap a run at one record.
    """
    limit = action_config.get("record_limit")
    if isinstance(limit, bool) or not isinstance(limit, int):
        return None
    return limit if limit > 0 else None
