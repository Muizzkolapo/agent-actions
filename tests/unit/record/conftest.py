"""Shared fixtures for record module tests."""

import pytest

from agent_actions.record.envelope import _reset_truncation_log_state_for_tests


@pytest.fixture(autouse=True)
def _reset_state_history_truncation_log():
    _reset_truncation_log_state_for_tests()
    yield
    _reset_truncation_log_state_for_tests()
