"""A record sent to another branch: filtered where it left, not dead below."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_actions.record.reasons import GUARD_FILTER, SENT_ELSEWHERE

# Internal action keys, written by the renderer: a record this action's guard filters
# went to another branch; records sent elsewhere above this action come back here.
SENDS_ELSEWHERE_KEY = "_sends_elsewhere"
GATHERS_KEY = "_gathers"


def sends_elsewhere(config: Mapping[str, Any] | None) -> bool:
    return config is not None and config.get(SENDS_ELSEWHERE_KEY) is True


def gathers(config: Mapping[str, Any] | None) -> bool:
    return config is not None and config.get(GATHERS_KEY) is True


def guard_filter_reason(config: Mapping[str, Any] | None) -> str:
    """The reason a record this action's guard filters is recorded with."""
    return SENT_ELSEWHERE if sends_elsewhere(config) else GUARD_FILTER
