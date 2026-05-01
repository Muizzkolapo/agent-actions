"""Helpers for building target-shaped records in tests."""

from __future__ import annotations

from typing import Any

from agent_actions.record.state import STATE_SCHEMA_VERSION, RecordState


def with_target_lifecycle(
    record: dict[str, Any],
    *,
    state: RecordState | str = RecordState.PROCESSED,
) -> dict[str, Any]:
    """Return *record* merged with required frozen-target lifecycle fields."""
    st = state.value if isinstance(state, RecordState) else state
    out = dict(record)
    out["_state"] = st
    out["_state_schema_version"] = STATE_SCHEMA_VERSION
    return out
