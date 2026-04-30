"""Record state machine primitives.

Every pipeline dict must carry ``record["_state"]`` (a :class:`RecordState` value).
Initial staging calls :meth:`RecordEnvelope.admit_staging_row` so loader rows are
lifecycle-ready; :meth:`RecordState.from_record` and :meth:`RecordEnvelope.transition`
require the field thereafter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast


class RecordStateTransitionError(Exception):
    """Invalid lifecycle transition or malformed transition reason."""

    pass


class InvalidRecordStateError(ValueError):
    """``record['_state']`` is missing, or present but not a valid :class:`RecordState`."""

    pass


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
        """Return the record's lifecycle state.

        ``_state`` is **required** on every pipeline record. Build with
        :class:`RecordEnvelope` or set ``_state`` explicitly before passing the
        dict into processing.
        """

        raw = record.get("_state")
        if raw is None:
            raise InvalidRecordStateError(
                "record['_state'] is required — build with RecordEnvelope or set explicitly"
            )
        try:
            return cls(str(raw))
        except ValueError as e:
            raise InvalidRecordStateError(
                f"Invalid record _state value {raw!r} — must be a known RecordState"
            ) from e

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
    from_state: str
    to_state: str
    reason: dict[str, Any]
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp": self.timestamp,
            "action": self.action,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reason": self.reason,
        }
        if self.detail is not None:
            d["detail"] = self.detail
        return d


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_state_strict(record: dict[str, Any]) -> RecordState:
    """Same as :meth:`RecordState.from_record` — used at envelope transition time."""

    return RecordState.from_record(record)


def validate_transition_reason(reason: dict[str, Any]) -> str:
    if not isinstance(reason, dict):
        raise RecordStateTransitionError(
            f"Transition reason must be a dict, got {type(reason).__name__}"
        )
    rt = reason.get("type")
    if not isinstance(rt, str) or not rt:
        raise RecordStateTransitionError(
            "Transition reason must include a non-empty string 'type' field"
        )
    return rt


def validate_state_transition(
    from_st: RecordState,
    to_st: RecordState,
    reason: dict[str, Any],
) -> None:
    """Raise RecordStateTransitionError if the edge is not allowed."""

    rt = validate_transition_reason(reason)

    if rt == "downstream_reset":
        if to_st != RecordState.ACTIVE:
            raise RecordStateTransitionError(
                f"downstream_reset must target ACTIVE, got {to_st.value}"
            )
        if from_st not in RESETTABLE_DOWNSTREAM_STATES:
            raise RecordStateTransitionError(
                f"downstream_reset from illegal prior state {from_st.value!r}"
            )
        declared = reason.get("from_state")
        if declared != from_st.value:
            raise RecordStateTransitionError(
                f"downstream_reset reason from_state {declared!r} does not match "
                f"record prior state {from_st.value!r}"
            )
        return

    if from_st == to_st:
        if to_st == RecordState.CASCADE_SKIPPED and rt == "cascade":
            return
        raise RecordStateTransitionError(
            f"Illegal no-op transition {from_st.value!r} -> {to_st.value!r}"
        )

    if rt == "invoke" and to_st == RecordState.PROCESSED:
        if from_st != RecordState.ACTIVE:
            raise RecordStateTransitionError(
                f"invoke requires prior ACTIVE, got {from_st.value!r}"
            )
        return

    if rt == "invoke_reset" and to_st == RecordState.ACTIVE:
        if from_st != RecordState.PROCESSED:
            raise RecordStateTransitionError(
                f"invoke_reset requires prior PROCESSED, got {from_st.value!r}"
            )
        return

    if rt == "guard" and to_st in _GUARD_DISPOSITION_STATES:
        return

    if rt == "passthrough" and to_st == RecordState.GUARD_SKIPPED:
        if from_st != RecordState.ACTIVE:
            raise RecordStateTransitionError(
                f"passthrough guard skip requires prior ACTIVE, got {from_st.value!r}"
            )
        return

    if rt == "error" and to_st == RecordState.FAILED:
        if from_st == RecordState.FAILED:
            raise RecordStateTransitionError("Cannot re-mark failed on an already failed record")
        return

    if rt == "exhausted" and to_st == RecordState.EXHAUSTED:
        if from_st == RecordState.EXHAUSTED:
            raise RecordStateTransitionError(
                "Cannot re-mark exhausted on an already exhausted record"
            )
        return

    if rt == "cascade" and to_st == RecordState.CASCADE_SKIPPED:
        if from_st not in (RecordState.ACTIVE, RecordState.PROCESSED):
            raise RecordStateTransitionError(
                f"cascade skip requires prior ACTIVE or PROCESSED, got {from_st.value!r}"
            )
        return

    if rt == "commit" and to_st == RecordState.COMMITTED:
        if from_st not in (RecordState.ACTIVE, RecordState.PROCESSED):
            raise RecordStateTransitionError(
                f"commit requires prior ACTIVE or PROCESSED, got {from_st.value!r}"
            )
        return

    raise RecordStateTransitionError(
        f"Unsupported transition {from_st.value!r} -> {to_st.value!r} "
        f"for reason type {cast(str, rt)!r}"
    )


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
    from_state: RecordState,
    to_state: RecordState,
    reason: dict[str, Any],
    detail: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> None:
    transitions = ensure_transition_list(record)
    t = RecordTransition(
        timestamp=timestamp or now_iso(),
        action=action,
        from_state=from_state.value,
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


def reason_downstream_reset(*, from_state: str):
    return {"type": "downstream_reset", "from_state": from_state}


RESETTABLE_DOWNSTREAM_STATES: frozenset[RecordState] = frozenset(
    {RecordState.COMMITTED, RecordState.GUARD_SKIPPED, RecordState.GUARD_DEFERRED}
)

_GUARD_DISPOSITION_STATES: frozenset[RecordState] = frozenset(
    {
        RecordState.GUARD_SKIPPED,
        RecordState.GUARD_DEFERRED,
        RecordState.GUARD_FILTERED,
    }
)

CASCADE_BLOCKING_STATES: frozenset[RecordState] = frozenset(
    {RecordState.FAILED, RecordState.EXHAUSTED, RecordState.CASCADE_SKIPPED}
)


def is_any_state(record: dict[str, Any], states: Iterable[RecordState]) -> bool:
    state = RecordState.from_record(record)
    return state in set(states)
