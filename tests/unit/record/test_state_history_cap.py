"""Regression tests for VIOL-0024: silent _state_history truncation.

The cap itself is intentional. What we're guarding against is (a) the doc
math drifting from the constant, and (b) the truncation being invisible in
logs. The dedup key is action_name — one log per action per process.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.record.envelope import (
    STATE_HISTORY_CAP,
    RecordEnvelope,
    _reset_truncation_log_state_for_tests,
)
from agent_actions.record.state import RecordState


def _drive_transitions(n: int, action_name: str = "act") -> dict:
    """Push a record through n legal ACTIVE→ACTIVE transitions."""
    record: dict = {}
    for _ in range(n):
        RecordEnvelope.transition(record, RecordState.ACTIVE, action_name, "test")
    return record


@pytest.fixture
def envelope_log_propagates():
    # LoggingFactory sets `agent_actions` propagate=False once initialized in a
    # prior test. Caplog attaches at root, so without propagation the truncation
    # log never reaches it. Restore the original value after the test to avoid
    # polluting downstream tests that assert on logger-bridge behavior.
    root = logging.getLogger("agent_actions")
    original = root.propagate
    root.propagate = True
    try:
        yield
    finally:
        root.propagate = original


def test_cap_constant_is_64():
    assert STATE_HISTORY_CAP == 64


def test_transitioning_past_cap_trims_oldest_entries():
    _reset_truncation_log_state_for_tests()
    record = _drive_transitions(STATE_HISTORY_CAP + 5)
    history = record["_state_history"]
    assert len(history) == STATE_HISTORY_CAP
    assert history[-1]["reason"] == "test"


def test_first_truncation_for_action_logs_once(caplog, envelope_log_propagates):
    _reset_truncation_log_state_for_tests()
    with caplog.at_level(logging.INFO, logger="agent_actions.record.envelope"):
        _drive_transitions(STATE_HISTORY_CAP + 1, action_name="act_a")
        _drive_transitions(STATE_HISTORY_CAP + 1, action_name="act_a")
    truncation_logs = [
        r
        for r in caplog.records
        if "_state_history" in r.getMessage() and "capped" in r.getMessage()
    ]
    assert len(truncation_logs) == 1, [r.getMessage() for r in truncation_logs]
    msg = truncation_logs[0].getMessage()
    assert "64" in msg
    assert "act_a" in msg


def test_distinct_actions_log_independently(caplog, envelope_log_propagates):
    _reset_truncation_log_state_for_tests()
    with caplog.at_level(logging.INFO, logger="agent_actions.record.envelope"):
        _drive_transitions(STATE_HISTORY_CAP + 1, action_name="act_a")
        _drive_transitions(STATE_HISTORY_CAP + 1, action_name="act_b")
    truncation_logs = [
        r
        for r in caplog.records
        if "_state_history" in r.getMessage() and "capped" in r.getMessage()
    ]
    assert len(truncation_logs) == 2
    logged_actions = {r.getMessage() for r in truncation_logs}
    assert any("act_a" in m for m in logged_actions)
    assert any("act_b" in m for m in logged_actions)


def test_no_log_when_under_cap(caplog, envelope_log_propagates):
    _reset_truncation_log_state_for_tests()
    with caplog.at_level(logging.INFO, logger="agent_actions.record.envelope"):
        _drive_transitions(STATE_HISTORY_CAP, action_name="act_under")
    truncation_logs = [
        r
        for r in caplog.records
        if "_state_history" in r.getMessage() and "capped" in r.getMessage()
    ]
    assert truncation_logs == []
