"""Derive storage disposition from record lifecycle state."""

from __future__ import annotations

from typing import Any

from agent_actions.record.state import RecordState
from agent_actions.storage.backend import Disposition

_STATE_TO_DISPOSITION: dict[RecordState, Disposition] = {
    RecordState.PROCESSED: Disposition.SUCCESS,
    RecordState.COMMITTED: Disposition.SUCCESS,
    RecordState.GUARD_SKIPPED: Disposition.PASSTHROUGH,
    RecordState.CASCADE_SKIPPED: Disposition.UNPROCESSED,
    RecordState.GUARD_DEFERRED: Disposition.DEFERRED,
    RecordState.FAILED: Disposition.FAILED,
    RecordState.EXHAUSTED: Disposition.EXHAUSTED,
    RecordState.ACTIVE: Disposition.PASSTHROUGH,
}


def derive_disposition(record: dict[str, Any]) -> str:
    """Map a record's ``_state`` to its storage disposition value."""
    state = RecordState(record["_state"])
    return _STATE_TO_DISPOSITION[state].value
