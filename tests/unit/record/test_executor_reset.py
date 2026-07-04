"""Tests for executor boundary reset (P5-040)."""

from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.lifecycle_read import reset_for_downstream
from agent_actions.record.state import RecordState


def _record(state: str) -> dict:
    """Create a record with a given _state via transition."""
    rec: dict = {}
    RecordEnvelope.transition(rec, RecordState(state), "upstream_action", "test")
    return rec


class TestResetForDownstream:
    """Tests for reset_for_downstream() — executor boundary reset."""

    def test_processed_resets_to_active(self):
        records = [_record("processed")]
        reset_for_downstream(records, action_name="downstream")
        assert records[0]["_state"] == "active"

    def test_guard_skipped_resets_to_active(self):
        records = [_record("guard_skipped")]
        reset_for_downstream(records, action_name="downstream")
        assert records[0]["_state"] == "active"

    def test_cascade_skipped_stays(self):
        records = [_record("cascade_skipped")]
        reset_for_downstream(records, action_name="downstream")
        assert records[0]["_state"] == "cascade_skipped"

    def test_failed_stays(self):
        records = [_record("failed")]
        reset_for_downstream(records, action_name="downstream")
        assert records[0]["_state"] == "failed"

    def test_exhausted_stays(self):
        records = [_record("exhausted")]
        reset_for_downstream(records, action_name="downstream")
        assert records[0]["_state"] == "exhausted"

    def test_active_stays(self):
        records = [_record("active")]
        reset_for_downstream(records, action_name="downstream")
        assert records[0]["_state"] == "active"

    def test_reset_appends_history(self):
        records = [_record("processed")]
        reset_for_downstream(records, action_name="downstream")
        history = records[0]["_state_history"]
        last_entry = history[-1]
        assert last_entry["from"] == "processed"
        assert last_entry["to"] == "active"
        assert last_entry["action"] == "downstream"
        assert last_entry["reason"] == "downstream_reset"

    def test_cascade_blocking_no_history_added(self):
        records = [_record("failed")]
        history_len_before = len(records[0]["_state_history"])
        reset_for_downstream(records, action_name="downstream")
        assert len(records[0]["_state_history"]) == history_len_before

    def test_mixed_batch(self):
        records = [
            _record("processed"),
            _record("cascade_skipped"),
            _record("guard_skipped"),
            _record("failed"),
        ]
        reset_for_downstream(records, action_name="next_action")
        assert records[0]["_state"] == "active"
        assert records[1]["_state"] == "cascade_skipped"
        assert records[2]["_state"] == "active"
        assert records[3]["_state"] == "failed"
