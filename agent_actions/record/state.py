"""Record state machine primitives.

This module provides a single, typed source of truth for record lifecycle state
within a pipeline run. The state is stored on each record as `record["_state"]`
and transitions are recorded as a list under `record["_transitions"]`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class RecordState(str, Enum):
    """Per-action record lifecycle state.

    Stored as a string in `record["_state"]`.
    """

    ACTIVE = "active"
    PROCESSED = "processed"  # transient (should not be persisted)
    COMMITTED = "committed"

    GUARD_SKIPPED = "guard_skipped"
    GUARD_DEFERRED = "guard_deferred"
    GUARD_FILTERED = "guard_filtered"

    FAILED = "failed"
    EXHAUSTED = "exhausted"
    CASCADE_SKIPPED = "cascade_skipped"

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> RecordState:
        """Parse state from a record, defaulting to ACTIVE when absent.

        During the cutover we may still encounter records without `_state`;
        treating those as ACTIVE keeps processing stable until all producers
        are migrated.
        """

        raw = record.get("_state")
        if raw is None:
            return cls.ACTIVE
        try:
            return cls(str(raw))
        except ValueError:
            # Unknown state value; treat as ACTIVE so the pipeline can proceed,
            # while still surfacing the raw value via transitions/dispositions.
            return cls.ACTIVE

    def is_processable(self) -> bool:
        """Return True if the record can be processed in the current action."""

        return self in (RecordState.ACTIVE, RecordState.PROCESSED)

    def is_settled(self) -> bool:
        """Return True if the record is final for this action in this run."""

        return not self.is_processable()

    def is_retriable(self) -> bool:
        """Return True if a future rerun could legitimately retry this record."""

        return self in (
            RecordState.FAILED,
            RecordState.EXHAUSTED,
            RecordState.CASCADE_SKIPPED,
            RecordState.GUARD_DEFERRED,
        )


@dataclass(frozen=True)
class RecordTransition:
    """A single state transition entry stored on the record."""

    timestamp: str
    action: str
    to_state: str
    reason: dict[str, Any]
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp": self.timestamp,
            "action": self.action,
            "to_state": self.to_state,
            "reason": self.reason,
        }
        if self.detail is not None:
            d["detail"] = self.detail
        return d


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_transition_list(record: dict[str, Any]) -> list[dict[str, Any]]:
    transitions = record.get("_transitions")
    if isinstance(transitions, list):
        return transitions
    transitions_list: list[dict[str, Any]] = []
    record["_transitions"] = transitions_list
    return transitions_list


def append_transition(
    record: dict[str, Any],
    *,
    action: str,
    to_state: RecordState,
    reason: dict[str, Any],
    detail: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> None:
    transitions = ensure_transition_list(record)
    t = RecordTransition(
        timestamp=timestamp or now_iso(),
        action=action,
        to_state=to_state.value,
        reason=reason,
        detail=detail,
    )
    transitions.append(t.to_dict())


def reason_guard(*, clause: str, behavior: str, result: bool, values: dict[str, Any] | None = None):
    r: dict[str, Any] = {
        "type": "guard",
        "clause": clause,
        "behavior": behavior,
        "result": result,
    }
    if values is not None:
        r["values"] = values
    return r


def reason_error(*, error_type: str, message: str):
    return {"type": "error", "error_type": error_type, "message": message}


def reason_exhausted(
    *, attempts: int | str, last_error: str | None = None, model: str | None = None
):
    r: dict[str, Any] = {"type": "exhausted", "attempts": attempts}
    if last_error is not None:
        r["last_error"] = last_error
    if model is not None:
        r["model"] = model
    return r


def reason_cascade(
    *, upstream_action: str, upstream_state: str, upstream_reason: dict[str, Any] | None = None
):
    r: dict[str, Any] = {
        "type": "cascade",
        "upstream_action": upstream_action,
        "upstream_state": upstream_state,
    }
    if upstream_reason is not None:
        r["upstream_reason"] = upstream_reason
    return r


RESETTABLE_DOWNSTREAM_STATES: frozenset[RecordState] = frozenset(
    {RecordState.COMMITTED, RecordState.GUARD_SKIPPED, RecordState.GUARD_DEFERRED}
)

CASCADE_BLOCKING_STATES: frozenset[RecordState] = frozenset(
    {RecordState.FAILED, RecordState.EXHAUSTED, RecordState.CASCADE_SKIPPED}
)


def is_any_state(record: dict[str, Any], states: Iterable[RecordState]) -> bool:
    state = RecordState.from_record(record)
    return state in set(states)
