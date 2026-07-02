from __future__ import annotations

import logging

from agent_actions.record.envelope import (
    STATE_HISTORY_CAP,
    RecordEnvelope,
)
from agent_actions.record.state import RecordState


def _drive_transitions(n: int, action_name: str = "act") -> dict:
    record: dict = {}
    for _ in range(n):
        RecordEnvelope.transition(record, RecordState.ACTIVE, action_name, "test")
    return record


def _truncation_records(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if "_state_history" in r.getMessage() and "capped" in r.getMessage()
    ]


def test_first_truncation_for_action_logs_once(caplog):
    with caplog.at_level(logging.WARNING, logger="agent_actions.record.envelope"):
        _drive_transitions(STATE_HISTORY_CAP + 1, action_name="act_a")
        _drive_transitions(STATE_HISTORY_CAP + 1, action_name="act_a")
    truncation_logs = _truncation_records(caplog)
    assert len(truncation_logs) == 1, [r.getMessage() for r in truncation_logs]
    msg = truncation_logs[0].getMessage()
    assert "64" in msg
    assert "act_a" in msg


def test_distinct_actions_log_independently(caplog):
    with caplog.at_level(logging.WARNING, logger="agent_actions.record.envelope"):
        _drive_transitions(STATE_HISTORY_CAP + 1, action_name="act_a")
        _drive_transitions(STATE_HISTORY_CAP + 1, action_name="act_b")
    truncation_logs = _truncation_records(caplog)
    assert len(truncation_logs) == 2
    logged_actions = {r.getMessage() for r in truncation_logs}
    assert any("act_a" in m for m in logged_actions)
    assert any("act_b" in m for m in logged_actions)


def test_no_log_when_under_cap(caplog):
    with caplog.at_level(logging.WARNING, logger="agent_actions.record.envelope"):
        _drive_transitions(STATE_HISTORY_CAP, action_name="act_under")
    assert _truncation_records(caplog) == []


def test_over_cap_input_reports_full_overflow(caplog):
    # A record hydrated from an older/higher cap arrives with history already
    # over the cap; the log's dropped=N reflects the full overflow, not just
    # the entry appended by this call.
    oversized = STATE_HISTORY_CAP + 10
    record: dict = {
        "_state_history": [
            {
                "timestamp": "1970-01-01T00:00:00+00:00",
                "action": "seed",
                "from": None,
                "to": "active",
                "reason": "seed",
                "detail": None,
            }
            for _ in range(oversized)
        ],
    }
    with caplog.at_level(logging.WARNING, logger="agent_actions.record.envelope"):
        RecordEnvelope.transition(record, RecordState.ACTIVE, "act_rehydrated", "test")
    truncation_logs = _truncation_records(caplog)
    assert len(truncation_logs) == 1
    # Appended 1 entry to oversized+1; overflow = (oversized+1) - CAP = 11.
    assert "11" in truncation_logs[0].getMessage()
    assert len(record["_state_history"]) == STATE_HISTORY_CAP
