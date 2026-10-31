"""Tests for executor boundary reset (P5-040)."""

import pytest

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

    @pytest.mark.parametrize(
        ("state", "after"),
        [
            pytest.param("processed", "active", id="processed-resets-to-active"),
            pytest.param("guard_skipped", "active", id="guard_skipped-resets-to-active"),
            pytest.param("cascade_skipped", "cascade_skipped", id="cascade_skipped-stays"),
            pytest.param("failed", "failed", id="failed-stays"),
            pytest.param("exhausted", "exhausted", id="exhausted-stays"),
            pytest.param("active", "active", id="active-stays"),
        ],
    )
    def test_reset_moves_state(self, state, after):
        records = [_record(state)]
        reset_for_downstream(records, action_name="downstream")
        assert records[0]["_state"] == after

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
