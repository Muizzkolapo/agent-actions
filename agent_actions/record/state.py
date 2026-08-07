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
    GUARD_SKIPPED = "guard_skipped"
    CASCADE_SKIPPED = "cascade_skipped"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


PROCESSABLE_STATES: frozenset[RecordState] = frozenset({RecordState.ACTIVE})

RESETTABLE_DOWNSTREAM_STATES: frozenset[RecordState] = frozenset(
    {
        RecordState.PROCESSED,
        RecordState.GUARD_SKIPPED,
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
