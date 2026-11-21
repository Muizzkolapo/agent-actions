"""How `agac run` and `agac retry` end: the outcome of the workflow and its exit code."""

from __future__ import annotations

from enum import Enum
from typing import Any

EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_RECORD_FAILURES = 3
EXIT_PAUSED = 4


class RunOutcome(str, Enum):
    """What the action statuses say once a run or a retry has stopped."""

    SUCCESS = "success"
    RECORD_FAILURES = "record_failures"
    PAUSED_FOR_BATCH = "paused_for_batch"
    PAUSED = "paused"
    FAILED = "failed"


EXIT_CODES: dict[RunOutcome, int] = {
    RunOutcome.SUCCESS: EXIT_SUCCESS,
    RunOutcome.RECORD_FAILURES: EXIT_RECORD_FAILURES,
    RunOutcome.PAUSED_FOR_BATCH: EXIT_PAUSED,
    RunOutcome.PAUSED: EXIT_PAUSED,
    RunOutcome.FAILED: EXIT_FAILED,
}

# The run history keeps its three statuses; the documentation site reads no other.
TRACKER_STATUSES: dict[RunOutcome, str] = {
    RunOutcome.SUCCESS: "SUCCESS",
    RunOutcome.RECORD_FAILURES: "SUCCESS",
    RunOutcome.PAUSED_FOR_BATCH: "PAUSED",
    RunOutcome.PAUSED: "PAUSED",
    RunOutcome.FAILED: "FAILED",
}


def run_status(state_mgr: Any) -> str:
    """The status the run history keeps for these action statuses: SUCCESS, PAUSED or FAILED.

    An action that completed holding failed or exhausted records is complete, so the
    workflow finished.
    """
    if state_mgr.is_workflow_complete():
        return "SUCCESS"
    if not state_mgr.is_workflow_done():
        return "PAUSED"
    return "FAILED" if state_mgr.has_any_failed() else "SUCCESS"


def classify_outcome(state_mgr: Any, execution_order: list[str]) -> RunOutcome:
    """The outcome the action statuses stand for: `run_status`, told apart further.

    A pause is for a batch when an action waits on one, and a finished workflow has
    record failures when an action completed holding a failed or exhausted record.
    """
    status = run_status(state_mgr)
    if status == "FAILED":
        return RunOutcome.FAILED
    if status == "PAUSED":
        if state_mgr.get_batch_submitted_actions(execution_order):
            return RunOutcome.PAUSED_FOR_BATCH
        return RunOutcome.PAUSED
    if actions_with_record_failures(state_mgr, execution_order):
        return RunOutcome.RECORD_FAILURES
    return RunOutcome.SUCCESS


def actions_with_record_failures(state_mgr: Any, execution_order: list[str]) -> list[str]:
    """The actions that completed holding failed or exhausted records."""
    return [action for action in execution_order if state_mgr.is_completed_with_failures(action)]
