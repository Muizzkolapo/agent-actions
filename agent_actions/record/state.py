"""Record lifecycle state machine.

``RecordState`` is the single source of truth for where a record sits in the
pipeline lifecycle.  Every record carries a ``_state`` field whose value is
one of these enum members.
"""

from __future__ import annotations

from enum import Enum


class RecordState(str, Enum):
    """Lifecycle state of a pipeline record."""

    ACTIVE = "active"
    PROCESSED = "processed"
    COMMITTED = "committed"
    GUARD_SKIPPED = "guard_skipped"
    GUARD_DEFERRED = "guard_deferred"
    CASCADE_SKIPPED = "cascade_skipped"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


PROCESSABLE_STATES: frozenset[RecordState] = frozenset({RecordState.ACTIVE})

SETTLED_STATES: frozenset[RecordState] = frozenset(RecordState) - PROCESSABLE_STATES

RESETTABLE_DOWNSTREAM_STATES: frozenset[RecordState] = frozenset(
    {
        RecordState.PROCESSED,
        RecordState.COMMITTED,
        RecordState.GUARD_SKIPPED,
        RecordState.GUARD_DEFERRED,
    }
)

CASCADE_BLOCKING_STATES: frozenset[RecordState] = frozenset(
    {
        RecordState.CASCADE_SKIPPED,
        RecordState.FAILED,
        RecordState.EXHAUSTED,
    }
)

CASCADE_BLOCKING_VALUES: frozenset[str] = frozenset(s.value for s in CASCADE_BLOCKING_STATES)

RETRIABLE_STATES: frozenset[RecordState] = frozenset(
    {
        RecordState.FAILED,
        RecordState.EXHAUSTED,
    }
)


def is_processable(state: RecordState) -> bool:
    """True if the record can be sent to an LLM/tool for processing."""
    return state in PROCESSABLE_STATES


def is_settled(state: RecordState) -> bool:
    """True if the record has reached a terminal state for this action."""
    return state in SETTLED_STATES


def is_retriable(state: RecordState) -> bool:
    """True if the record is in a retriable terminal state (FAILED or EXHAUSTED)."""
    return state in RETRIABLE_STATES
