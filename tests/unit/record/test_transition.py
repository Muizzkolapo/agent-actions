"""Tests for RecordEnvelope.transition() — lifecycle state mutator."""

import pytest

from agent_actions.record.envelope import (
    RECORD_FRAMEWORK_FIELDS,
    RECORD_STAGE_FIELDS,
    STATE_HISTORY_CAP,
    RecordEnvelope,
    RecordEnvelopeError,
)
from agent_actions.record.state import RecordState


def _active_record() -> dict:
    return {"_state": "active", "content": {}, "source_guid": "sg-1"}


def _record(state: RecordState) -> dict:
    return {"_state": state.value, "content": {}}


class TestTransitionBasic:
    def test_sets_state(self):
        rec = _active_record()
        RecordEnvelope.transition(rec, RecordState.PROCESSED, "act", "done")
        assert rec["_state"] == "processed"

    def test_sets_schema_version(self):
        rec = _active_record()
        RecordEnvelope.transition(rec, RecordState.PROCESSED, "act", "done")
        assert rec["_state_schema_version"] == 1

    def test_returns_record(self):
        rec = _active_record()
        result = RecordEnvelope.transition(rec, RecordState.PROCESSED, "act", "done")
        assert result is rec

    def test_history_entry_shape(self):
        rec = _active_record()
        RecordEnvelope.transition(rec, RecordState.PROCESSED, "my_action", "completed", detail="ok")
        entry = rec["_state_history"][0]
        assert entry["from"] == "active"
        assert entry["to"] == "processed"
        assert entry["action"] == "my_action"
        assert entry["reason"] == "completed"
        assert entry["detail"] == "ok"
        assert "timestamp" in entry

    def test_detail_none_stored(self):
        rec = _active_record()
        RecordEnvelope.transition(rec, RecordState.PROCESSED, "act", "done")
        assert rec["_state_history"][0]["detail"] is None

    def test_first_transition_from_none(self):
        rec = {"content": {}}
        RecordEnvelope.transition(rec, RecordState.ACTIVE, "init", "bootstrap")
        assert rec["_state"] == "active"
        assert rec["_state_history"][0]["from"] is None


class TestTransitionLegalEdges:
    @pytest.mark.parametrize(
        "to_state",
        [
            RecordState.PROCESSED,
            RecordState.COMMITTED,
            RecordState.GUARD_SKIPPED,
            RecordState.GUARD_DEFERRED,
            RecordState.CASCADE_SKIPPED,
            RecordState.FAILED,
            RecordState.EXHAUSTED,
        ],
    )
    def test_active_to_any_settled(self, to_state):
        rec = _active_record()
        RecordEnvelope.transition(rec, to_state, "act", "reason")
        assert rec["_state"] == to_state.value

    @pytest.mark.parametrize(
        "from_state",
        [
            RecordState.PROCESSED,
            RecordState.COMMITTED,
            RecordState.GUARD_SKIPPED,
            RecordState.GUARD_DEFERRED,
        ],
    )
    def test_resettable_to_active(self, from_state):
        rec = _record(from_state)
        RecordEnvelope.transition(rec, RecordState.ACTIVE, "reset", "retry")
        assert rec["_state"] == "active"

    def test_idempotent_same_state(self):
        rec = _active_record()
        RecordEnvelope.transition(rec, RecordState.ACTIVE, "act", "noop")
        assert rec["_state"] == "active"
        assert len(rec["_state_history"]) == 1

    @pytest.mark.parametrize(
        "from_state",
        [
            RecordState.CASCADE_SKIPPED,
            RecordState.FAILED,
            RecordState.EXHAUSTED,
        ],
    )
    def test_cascade_blocking_to_cascade_skipped(self, from_state):
        """CASCADE_BLOCKING states can transition to CASCADE_SKIPPED (cascade propagation)."""
        rec = _record(from_state)
        RecordEnvelope.transition(rec, RecordState.CASCADE_SKIPPED, "downstream", "cascade")
        assert rec["_state"] == "cascade_skipped"


class TestTransitionIllegalEdges:
    @pytest.mark.parametrize(
        "from_state",
        [
            RecordState.CASCADE_SKIPPED,
            RecordState.FAILED,
            RecordState.EXHAUSTED,
        ],
    )
    def test_cascade_blocking_cannot_reset_to_active(self, from_state):
        rec = _record(from_state)
        with pytest.raises(RecordEnvelopeError, match=f"{from_state.value!r}.*active"):
            RecordEnvelope.transition(rec, RecordState.ACTIVE, "act", "reset")

    def test_processed_cannot_go_to_failed(self):
        rec = _record(RecordState.PROCESSED)
        with pytest.raises(RecordEnvelopeError, match="'processed'.*'failed'"):
            RecordEnvelope.transition(rec, RecordState.FAILED, "act", "oops")

    def test_committed_cannot_go_to_guard_skipped(self):
        rec = _record(RecordState.COMMITTED)
        with pytest.raises(RecordEnvelopeError, match="'committed'.*'guard_skipped'"):
            RecordEnvelope.transition(rec, RecordState.GUARD_SKIPPED, "act", "reason")

    def test_unknown_state_value_raises_envelope_error(self):
        rec = {"_state": "bogus_state", "content": {}}
        with pytest.raises(RecordEnvelopeError, match="unknown _state value.*bogus_state"):
            RecordEnvelope.transition(rec, RecordState.PROCESSED, "act", "reason")

    def test_corrupt_history_type_raises_envelope_error(self):
        rec = {"_state": "active", "_state_history": "not-a-list", "content": {}}
        with pytest.raises(RecordEnvelopeError, match="_state_history must be a list"):
            RecordEnvelope.transition(rec, RecordState.PROCESSED, "act", "reason")

    def test_empty_action_name_raises(self):
        rec = _active_record()
        with pytest.raises(RecordEnvelopeError, match="action_name is required"):
            RecordEnvelope.transition(rec, RecordState.PROCESSED, "", "reason")


class TestTransitionHistoryCap:
    def test_history_grows_to_cap(self):
        rec = {"content": {}}
        for i in range(STATE_HISTORY_CAP):
            rec["_state"] = "active"
            RecordEnvelope.transition(rec, RecordState.PROCESSED, "act", f"step-{i}")
            rec["_state"] = "processed"
            RecordEnvelope.transition(rec, RecordState.ACTIVE, "reset", f"reset-{i}")
        assert len(rec["_state_history"]) == STATE_HISTORY_CAP

    def test_oldest_entry_dropped_at_cap(self):
        rec = {"content": {}}
        # Fill to cap
        for i in range(STATE_HISTORY_CAP):
            rec["_state"] = "active"
            RecordEnvelope.transition(rec, RecordState.PROCESSED, "act", f"step-{i}")
            rec["_state"] = "processed"
            if i < STATE_HISTORY_CAP - 1:
                RecordEnvelope.transition(rec, RecordState.ACTIVE, "reset", f"reset-{i}")

        first_reason_before_cap = rec["_state_history"][0]["reason"]

        # One more transition pushes oldest off
        rec["_state"] = "processed"
        RecordEnvelope.transition(rec, RecordState.ACTIVE, "reset", "overflow")
        assert len(rec["_state_history"]) == STATE_HISTORY_CAP
        assert rec["_state_history"][0]["reason"] != first_reason_before_cap
        assert rec["_state_history"][-1]["reason"] == "overflow"


class TestFrameworkFields:
    def test_state_fields_in_record_stage_fields(self):
        assert "_state" in RECORD_STAGE_FIELDS
        assert "_state_history" in RECORD_STAGE_FIELDS
        assert "_state_schema_version" in RECORD_STAGE_FIELDS

    def test_state_fields_in_framework_fields(self):
        assert "_state" in RECORD_FRAMEWORK_FIELDS
        assert "_state_history" in RECORD_FRAMEWORK_FIELDS
        assert "_state_schema_version" in RECORD_FRAMEWORK_FIELDS
