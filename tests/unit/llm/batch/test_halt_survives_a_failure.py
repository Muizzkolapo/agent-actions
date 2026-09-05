"""A parked halt is not lost when something else fails on the way to the finaliser.

Every early return past a park is guarded, but the exception exit is not a
return. Anything raised between the park and the finaliser unwinds past every
guard, and the outer loop answers a non-RuntimeError by logging it and moving to
the next file — so `on_exhausted: raise` finishes the run reporting success.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.errors import (
    ConfigurationError,
    DependencyError,
    ProcessingError,
    exhaustion_halt,
    raised_by_exhaustion_policy,
)
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


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("v"),
        KeyError("k"),
        TypeError("t"),
        OSError("o"),
        # The framework's own families. Builtins alone cannot see a boundary drawn
        # at AgentActionsError or ConfigurationError — both stay green against
        # ValueError and friends while dropping the halt for everything real.
        ProcessingError("provider rejected the payload"),
        ConfigurationError("record is missing _state"),
        DependencyError("upstream action produced nothing"),
    ],
)
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


def _guarded_calls(func) -> set[str]:
    """Names called inside a `with halt_survives_failure(...)` body, from the AST.

    A source-text search is satisfied by a comment, a docstring, or a `with`
    around `pass` — all of which were verified to pass the previous version of
    this check while the guard protected nothing.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        opens = {
            getattr(item.context_expr.func, "id", "") or getattr(item.context_expr.func, "attr", "")
            for item in node.items
            if isinstance(item.context_expr, ast.Call)
        }
        if not any("halt_survives_failure" in name for name in opens):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                name = getattr(inner.func, "id", "") or getattr(inner.func, "attr", "")
                if name:
                    guarded.add(name)
    return guarded


def test_every_entry_point_runs_its_real_work_inside_the_wrapper():
    """Not that the name appears — that the work happens inside the block."""
    from agent_actions.llm.batch.services import processing, processing_recovery

    expected = {
        processing_recovery.process_recovery_batch: {"handler"},
        processing.BatchProcessingService._process_original_batch: {
            "_check_and_submit_reprompt",
            "_check_and_submit_repair_impl",
            "_finalize_batch_output",
        },
        processing.BatchProcessingService._convert_batch_results_to_workflow_format: {
            "enrich_and_collect"
        },
    }
    for func, must_be_guarded in expected.items():
        guarded = _guarded_calls(func)
        missing = must_be_guarded - guarded
        assert not missing, (
            f"{func.__qualname__} calls {sorted(missing)} outside its "
            "halt_survives_failure block, so a failure there discards the halt"
        )
