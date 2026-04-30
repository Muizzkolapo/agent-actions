"""Tests for downstream state reset and cascade-blocking semantics."""

from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.record.state import RecordState


def test_guard_skipped_resets_to_active_for_downstream_processing() -> None:
    item = {"content": {"upstream": {"x": 1}}, "_state": RecordState.GUARD_SKIPPED.value}
    TaskPreparer._reset_state_for_downstream(item)
    assert item["_state"] == RecordState.ACTIVE.value
    assert TaskPreparer._is_upstream_unprocessed(item) is False


def test_failed_remains_cascade_blocking() -> None:
    item = {"content": {"upstream": {"x": 1}}, "_state": RecordState.FAILED.value}
    TaskPreparer._reset_state_for_downstream(item)
    assert item["_state"] == RecordState.FAILED.value
    assert TaskPreparer._is_upstream_unprocessed(item) is True
