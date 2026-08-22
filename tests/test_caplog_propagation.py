"""Guard for the suite-wide caplog propagation fixture in ``tests/conftest.py``.

``LoggerFactory._setup_logging_bridge`` sets ``propagate = False`` on the
``agent_actions`` logger (``logging/factory.py:257``) so its bridge handler owns
output. caplog hooks the Python root logger, so once any test configures the
framework's logging, every later caplog assertion sees nothing — presence
assertions fail confusingly and absence assertions pass no matter what the code
does.

The first two tests run in definition order and are the real guard: the first
leaves propagation disabled the way the framework does, the second fails unless
the fixture restored it. Delete the fixture and the second test goes red.
"""

import logging

AA_LOGGER = "agent_actions"


def test_a_simulates_the_framework_disabling_propagation():
    """Leave propagation off, exactly as LoggerFactory._setup_logging_bridge does.

    Deliberately dirties global logging state for the next test. The fixture's
    teardown restores it, so nothing leaks beyond this module.
    """
    logging.getLogger(AA_LOGGER).propagate = False
    assert logging.getLogger(AA_LOGGER).propagate is False


def test_b_fixture_restored_propagation_for_the_next_test():
    """Propagation is back on despite the previous test leaving it off.

    This is the assertion that fails if the autouse fixture is removed.
    """
    assert logging.getLogger(AA_LOGGER).propagate is True


def test_caplog_captures_agent_actions_records(caplog):
    """A record from an agent_actions logger actually reaches caplog."""
    caplog.set_level(logging.WARNING)
    logging.getLogger("agent_actions.probe").warning("propagation-probe-alpha")
    assert "propagation-probe-alpha" in caplog.text


def test_absence_assertions_are_not_vacuous(caplog):
    """caplog can see the record it is asked to prove absent.

    An absence assertion means nothing unless the same call would have been
    captured had it fired. Proves both halves in one test.
    """
    caplog.set_level(logging.WARNING)
    assert "propagation-probe-gamma" not in caplog.text
    logging.getLogger("agent_actions.probe").warning("propagation-probe-gamma")
    assert "propagation-probe-gamma" in caplog.text
