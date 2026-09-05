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


@pytest.mark.parametrize("failure", [ValueError("v"), KeyError("k"), TypeError("t"), OSError("o")])
def test_any_failure_type_preserves_the_halt(failure):
    """Not just the type the first test happened to raise.

    Narrowing the except clause to one exception type passes a suite whose
    failures are all that type, and leaves every other kind discarding the halt.
    """
    context = _context()
    context.pending_exhaustion = exhaustion_halt("Reprompt validation exhausted for rec-a")

    with pytest.raises(RuntimeError) as caught, halt_survives_failure(context):
        raise failure

    assert raised_by_exhaustion_policy(caught.value)
    assert caught.value.__cause__ is failure


def test_a_clean_pass_leaves_the_halt_parked_for_the_finaliser():
    context = _context()
    halt = exhaustion_halt("Reprompt validation exhausted for rec-a")
    context.pending_exhaustion = halt

    with halt_survives_failure(context):
        pass

    assert context.pending_exhaustion is halt, "the halt was consumed before the finaliser ran"


def test_every_context_builder_is_under_the_wrapper():
    """The guard is only worth what it covers.

    Two call paths build a RecoveryContext and park below it: the recovery
    dispatch and the original-batch path. A wrapper on one of them leaves the
    other exactly as exposed as before.
    """
    import inspect

    from agent_actions.llm.batch.services import processing, processing_recovery

    targets = [
        processing_recovery.process_recovery_batch,
        # A method, not a module attribute — resolving it off the module would
        # fall back to the whole file, where the import alone satisfies the check.
        processing.BatchProcessingService._process_original_batch,
    ]
    for target in targets:
        source = inspect.getsource(target)
        assert "RecoveryContext(" in source, f"{target.__qualname__} no longer builds a context"
        assert "halt_survives_failure" in source, (
            f"{target.__qualname__} builds a RecoveryContext and parks below it, "
            "but is not wrapped; an exception there discards the halt silently"
        )


def test_a_configuration_error_is_not_rebadged_as_a_policy_halt():
    """A broken expect: block is fix-the-config-and-rerun, not on_exhausted: raise.

    Substituting the halt would make raised_by_exhaustion_policy answer True, and
    the workflow layer then refuses to run the action on the next pass and
    excludes it from reset_retryable — so the operator fixes the YAML and the
    action stays pinned as halted.
    """
    from agent_actions.expectations.service import ExpectationConfigurationError

    context = _context()
    context.pending_exhaustion = exhaustion_halt("Retry exhausted for rec-a")
    broken_config = ExpectationConfigurationError("suite 'x' could not be loaded")

    with pytest.raises(ExpectationConfigurationError), halt_survives_failure(context):
        raise broken_config

    assert context.pending_exhaustion is not None, (
        "the halt was consumed by an error that is not a policy halt"
    )
