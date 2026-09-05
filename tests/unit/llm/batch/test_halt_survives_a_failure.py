"""A parked halt is not lost when something else fails on the way to the finaliser.

Every early return past a park is guarded, but the exception exit is not a
return. Anything raised between the park and the finaliser unwinds past every
guard, and the outer loop answers a non-RuntimeError by logging it and moving to
the next file — so `on_exhausted: raise` finishes the run reporting success.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.errors import exhaustion_halt, raised_by_exhaustion_policy
from agent_actions.llm.batch.services.processing_recovery import halt_survives_failure


def _context():
    context = MagicMock()
    context.pending_exhaustion = None
    return context


def test_an_unrelated_failure_does_not_discard_the_halt():
    context = _context()
    context.pending_exhaustion = exhaustion_halt("Reprompt validation exhausted for rec-a")

    with pytest.raises(RuntimeError) as caught, halt_survives_failure(context):
        raise ValueError("provider rejected the repair payload")

    assert raised_by_exhaustion_policy(caught.value), (
        "an incidental failure replaced the deliberate halt; the outer loop logs a "
        "non-RuntimeError and moves on, so the run finishes reporting success"
    )
    assert isinstance(caught.value.__cause__, ValueError), "the original cause was dropped"


def test_a_failure_with_nothing_parked_is_left_alone():
    with pytest.raises(ValueError, match="ordinary"), halt_survives_failure(_context()):
        raise ValueError("ordinary")


def test_a_clean_pass_leaves_the_halt_parked_for_the_finaliser():
    context = _context()
    halt = exhaustion_halt("Reprompt validation exhausted for rec-a")
    context.pending_exhaustion = halt

    with halt_survives_failure(context):
        pass

    assert context.pending_exhaustion is halt, "the halt was consumed before the finaliser ran"
