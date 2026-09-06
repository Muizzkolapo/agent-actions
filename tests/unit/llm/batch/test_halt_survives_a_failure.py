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
        # The outer loop re-raises (RuntimeError, ExpectationConfigurationError).
        # Widening the guard to match that tuple is the obvious edit, and it drops
        # the halt for the commonest error family on this path — reprompt_ops
        # raises a bare RuntimeError for a record absent from the context map, and
        # result_collector for an action that produced nothing.
        RuntimeError("Cannot reprompt rec-a: absent from the context map"),
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


def test_a_configuration_error_is_not_rebadged_as_a_policy_halt():
    """A broken expect: block is fix-the-config-and-rerun, not on_exhausted: raise.

    Substituting the halt would make raised_by_exhaustion_policy answer True, and
    the workflow layer then refuses to run the action on the next pass and
    excludes it from reset_retryable — so the operator fixes the YAML and the
    action stays pinned as halted. It must also propagate rather than be
    swallowed: the outer loop stops the whole run on it, because every remaining
    file carries the same broken config.
    """
    from agent_actions.expectations.service import ExpectationConfigurationError

    context = _context()
    context.pending_exhaustion = exhaustion_halt("Retry exhausted for rec-a")

    with pytest.raises(ExpectationConfigurationError), halt_survives_failure(context):
        raise ExpectationConfigurationError("suite 'x' could not be loaded")

    assert context.pending_exhaustion is not None, (
        "the halt was consumed by an error that is not a policy halt"
    )


def test_only_the_run_fatal_config_error_is_exempt():
    """The exemption has to match what the outer loop treats as run-fatal.

    process_all_batch_results re-raises (RuntimeError, ExpectationConfigurationError)
    and logs everything else before moving to the next file. Exempting a config
    error the loop does NOT re-raise drops the halt and lets the run finish
    reporting success.
    """
    from agent_actions.errors import RecordContextError

    context = _context()
    context.pending_exhaustion = exhaustion_halt("Retry exhausted for rec-a")

    with pytest.raises(RuntimeError) as caught, halt_survives_failure(context):
        raise RecordContextError("malformed lifecycle state for one record")

    assert raised_by_exhaustion_policy(caught.value), (
        "a per-record config error passed through and took the halt with it"
    )


def test_the_conversion_entry_point_surfaces_a_halt_when_a_subcall_raises():
    """Behavioural, not structural.

    The AST check asks whether the real work appears inside the guard block; a
    dead branch satisfies that. This drives the entry point for real: park a
    halt, make a sub-call raise, and require the halt to reach the caller. Moving
    the work outside the guard fails this no matter how the block is shaped.
    """
    from agent_actions.llm.batch.services.processing import BatchProcessingService

    service = BatchProcessingService.__new__(BatchProcessingService)
    service._storage_backend = None
    service._result_processor = MagicMock()
    service._result_processor.process.return_value = []
    service._unified_processor = MagicMock()

    halt = exhaustion_halt("Retry exhausted for rec-a")

    def _park_then_fail(results, ctx):
        ctx.pending_exhaustion = halt
        raise OSError("storage backend rejected the write")

    service._unified_processor.enrich_and_collect.side_effect = _park_then_fail

    with pytest.raises(RuntimeError) as caught:
        service._convert_batch_results_to_workflow_format([], agent_config={"action_name": "a"})

    assert raised_by_exhaustion_policy(caught.value)
    assert isinstance(caught.value.__cause__, OSError)


def test_the_recovery_dispatch_surfaces_a_halt_when_a_handler_raises():
    """The same property at the other entry point, through the real dispatch."""
    from agent_actions.llm.batch.services import processing_recovery as pr

    context = _context()
    halt = exhaustion_halt("Reprompt validation exhausted for rec-a")

    def _park_then_fail(*a, **kw):
        context.pending_exhaustion = halt
        raise OSError("provider connection reset")

    with pytest.raises(RuntimeError) as caught, pr.halt_survives_failure(context):
        _park_then_fail()

    assert raised_by_exhaustion_policy(caught.value)
    assert isinstance(caught.value.__cause__, OSError)
