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


def test_propagation_fixture_is_active(request):
    """The autouse fixture is applied and propagation is on.

    Deterministic and parallel-safe: asserts the fixture is actually in this
    test's fixture closure, so removing it or dropping ``autouse=True`` fails
    here regardless of execution order or xdist sharding. An order-dependent
    pair (dirty in one test, verify in the next) would silently pass under
    ``pytest -n``, since the two land on different workers.
    """
    assert "_enable_log_propagation" in request.fixturenames
    assert logging.getLogger(AA_LOGGER).propagate is True


def test_fixture_restores_propagation_after_a_test_disables_it(request):
    """Propagation is on at test start even though this test turns it off.

    The framework's own ``_setup_logging_bridge`` leaves ``propagate = False``
    behind; the fixture's job is to undo that for every subsequent test. This
    asserts the pre-state and then dirties it, so the fixture's teardown/setup
    is exercised for whatever runs next on this worker.
    """
    assert logging.getLogger(AA_LOGGER).propagate is True
    logging.getLogger(AA_LOGGER).propagate = False


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
