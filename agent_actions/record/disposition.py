"""Derive storage disposition from record lifecycle state.

Single mapping from final RecordState to SQLite disposition. All
record-level disposition writes should flow through derive_disposition().

Node-level dispositions (NODE_LEVEL_RECORD_ID / __node__) are set
explicitly by the executor based on aggregate action outcomes — they
do not use this function.
"""

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
    """Map a record's _state to its storage disposition value.

    Raises KeyError if _state is missing or not a valid RecordState.
    This should never happen after P5-023 validation — if it does,
    the pipeline has a bug.
    """
    state = RecordState(record["_state"])
    return _STATE_TO_DISPOSITION[state].value
