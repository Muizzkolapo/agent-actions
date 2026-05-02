"""Derive storage disposition from record lifecycle state."""

from __future__ import annotations

from typing import Any

from agent_actions.record.envelope import RecordEnvelopeError
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
    raw = record.get("_state")
    if raw is None:
        raise RecordEnvelopeError("Cannot derive disposition: record has no '_state' field")
    try:
        state = RecordState(raw)
    except ValueError:
        raise RecordEnvelopeError(
            f"Cannot derive disposition: unknown _state value {raw!r}"
        ) from None
    disposition = _STATE_TO_DISPOSITION.get(state)
    if disposition is None:
        raise RecordEnvelopeError(
            f"Cannot derive disposition: no mapping for state {state.value!r}"
        )
    return disposition.value
