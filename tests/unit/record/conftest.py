"""Shared fixtures for record module tests."""

import logging

import pytest

from agent_actions.record.envelope import _reset_truncation_log_state_for_tests


@pytest.fixture(autouse=True)
def _enable_log_propagation():
    """Ensure agent_actions loggers propagate to root so caplog captures them.

    The agent_actions root logger has propagate=False (set by LoggingBridgeHandler),
    so caplog (which hooks the Python root logger) can't see child log records.
    Temporarily enable propagation for the duration of each test.
    """
    aa_logger = logging.getLogger("agent_actions")
    orig = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = orig


@pytest.fixture(autouse=True)
def _reset_state_history_truncation_log():
    _reset_truncation_log_state_for_tests()
    yield
    _reset_truncation_log_state_for_tests()
