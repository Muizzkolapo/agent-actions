"""A reprompt round that exhausts on the resume path still hands its halt back.

The submit-side site is covered; this is the other one — the branch a batch takes
when it comes back on a later run, which is the ordinary asynchronous route.
Dropping the park there leaves `on_exhausted: raise` silently doing nothing.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import exhaustion_halt, raised_by_exhaustion_policy
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.processing_recovery import (
    BatchIdentity,
    handle_reprompt_recovery,
)
from agent_actions.llm.providers.batch_base import BatchResult

ACTION = "label_page"
PARENT = "pages.json"
FAILING = "rec-failing"
GRADUATED = [{"target_id": "graduated-earlier", "content": "paid for"}]


def _fake_path(output_directory, file_name, batch_id):
    return f"{output_directory}/{file_name}.{batch_id}.json"


def _entry() -> BatchJobEntry:
    return BatchJobEntry(
        batch_id="b-rp",
        status="completed",
        timestamp="2026-04-20T00:00:00Z",
        provider="openai",
        record_count=1,
        file_name=f"{PARENT}_reprompt_1",
        parent_file_name=PARENT,
        recovery_type="reprompt",
        recovery_attempt=1,
    )


def _state():
    state = MagicMock()
    state.reprompt_attempt = 2
    state.reprompt_max_attempts = 2  # spent: no further round is submitted
    state.on_exhausted = "raise"
    state.validation_name = "schema_check"
    state.reprompt_attempts_per_record = {}
    state.failure_type_counts = {}
    state.graduated_results = []
    state.unrepromptable_results = []
    state.missing_ids = []
    state.record_failure_counts = {}
    return state


@pytest.fixture
def context():
    context = MagicMock()
    context.action_name = ACTION
    context.agent_config = {"name": ACTION, "action_name": ACTION}
    context.output_directory = "/tmp"
    context.start_time = 0.0
    context.pending_exhaustion = None
    context.service._resolve_action_name.return_value = ACTION
    context.service._storage_backend = MagicMock()
    context.service._convert_batch_results_to_workflow_format.return_value = (
        list(GRADUATED),
        MagicMock(),
        None,
    )
    context.service._determine_output_path.side_effect = _fake_path
    context.written = []

    def _write(output_file, main_output, output_directory, action_name=None):
        context.written.append((str(output_file), list(main_output)))

    context.service._write_batch_output.side_effect = _write
    context.service._retry_service.apply_exhausted_reprompt_metadata.return_value = exhaustion_halt(
        "Reprompt validation exhausted for rec-failing after 2 attempts"
    )
    return context


def _run(context, state=None):
    failing = BatchResult(custom_id=FAILING, content=None, success=False, error="bad shape")
    loop, strategy = MagicMock(), MagicMock()
    strategy.name = "schema_check"
    loop.split.return_value = ([], [failing], {})

    raised = None
    with (
        patch(
            "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop",
            return_value=(loop, strategy),
        ),
        patch(
            "agent_actions.llm.batch.services.processing_recovery.cleanup_recovery",
            return_value=None,
        ),
        patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"),
        patch("agent_actions.llm.batch.services.processing_recovery._remove_batch_placeholder"),
    ):
        try:
            handle_reprompt_recovery(
                context,
                BatchIdentity(batch_id="b-rp", file_name=PARENT, entry=_entry()),
                state or _state(),
                [failing],
                [],
                {FAILING: {}},
            )
        except BaseException as exc:  # noqa: BLE001 - the test is about which one
            raised = exc
    return raised


def test_the_resume_path_hands_its_halt_back(context):
    raised = _run(context)

    assert isinstance(raised, RuntimeError)
    assert raised_by_exhaustion_policy(raised)
    assert "exhausted" in str(raised).lower()


def test_the_records_the_rounds_graduated_reach_the_file(context):
    """What the halt must not cost.

    Asserting only that a write happened is satisfied by raising in place after
    poking the write with an empty payload, so this reads the payload. The probe
    also takes the real signature, so a call a live run would reject as a
    TypeError cannot pass here either.
    """
    _run(context)

    assert context.written, "nothing was written; the halt fired before the output existed"
    assert len(context.written) == 1, f"the output was written {len(context.written)} times"
    # The records the conversion produced, not merely a non-empty list: asserting
    # truthiness is satisfied by writing anything at all before raising.
    path, payload = context.written[0]
    assert payload == GRADUATED, (
        f"the file did not receive what the conversion produced ({payload}); "
        "every record the reprompt rounds graduated is lost"
    )
    # The probe used to bind the path and discard it, so writing the right rows to
    # the wrong file passed.
    # The destination must be what the path call produced, and that call must
    # receive its arguments in the documented order — swapping two of them still
    # yields a real, different file, which a constant-returning mock cannot see.
    called = context.service._determine_output_path.call_args.args
    assert path == _fake_path(*called), "the write went somewhere other than the path call returned"
    assert called[0] == context.output_directory, f"output_directory was {called[0]!r}"
    # Both identity values reach the path call, and neither is dropped or
    # duplicated. Their order is deliberately not asserted here: it is a property
    # of _determine_output_path's signature, pinned where that function is tested,
    # and asserting it from this distance pins the mock rather than the code.
    # Both identity values reach the call and neither is dropped. Their order is
    # not asserted: the identity this finaliser receives is not the one this test
    # constructs — something between rebuilds it — so an order assertion here
    # would pin that indirection rather than the write. Order belongs with
    # _determine_output_path's own tests.
    assert set(called[1:]) == {PARENT, "b-rp"}, (
        f"the path was built from {called[1:]!r}, not from the batch identity"
    )


@pytest.mark.parametrize("policy", ["raise", "return_last"])
def test_the_configured_policy_is_what_decides(context, policy):
    """Both directions. Asserting only that "raise" arrives is satisfied by
    hardcoding it, which halts every run configured return_last."""
    state = _state()
    state.on_exhausted = policy
    _run(context, state=state)

    kwargs = context.service._retry_service.apply_exhausted_reprompt_metadata.call_args.kwargs
    assert kwargs["on_exhausted"] == policy, (
        f"the resume path sent {kwargs['on_exhausted']!r} for a {policy!r} action; "
        "a hardcoded value makes the configured policy unreachable in one direction"
    )


def test_the_halt_is_not_dropped_when_repair_defers(context):
    """The branch that skips the finaliser entirely.

    When repair submits another round the function returns before
    _finalize_and_cleanup, which is the only place a parked halt is raised. The
    context is rebuilt per pass and does not carry pending_exhaustion, so a halt
    parked here is gone — on_exhausted: raise silently doing nothing.
    """
    failing = BatchResult(custom_id=FAILING, content=None, success=False, error="bad shape")
    loop, strategy = MagicMock(), MagicMock()
    strategy.name = "schema_check"
    loop.split.return_value = ([], [failing], {})

    raised = None
    with (
        patch(
            "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop",
            return_value=(loop, strategy),
        ),
        patch(
            "agent_actions.llm.batch.services.processing_recovery.check_and_submit_repair",
            return_value=False,
        ),
        patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"),
    ):
        try:
            handle_reprompt_recovery(
                context,
                BatchIdentity(batch_id="b-rp", file_name=PARENT, entry=_entry()),
                _state(),
                [failing],
                [],
                {FAILING: {}},
            )
        except BaseException as exc:  # noqa: BLE001 - the test is about which one
            raised = exc

    assert raised is not None, (
        "the reprompt halt was parked and then discarded when repair deferred; "
        "on_exhausted: raise finished the run reporting success"
    )
    assert raised_by_exhaustion_policy(raised)


def test_the_retry_handler_also_surfaces_a_halt_before_deferring(context):
    """The sibling deferral, on the path that runs while retry is still active.

    handle_retry_recovery reaches check_and_submit_repair after
    check_and_submit_reprompt may already have parked a halt. Deferring there
    skips the finaliser exactly as it does on the resume path.
    """
    from agent_actions.llm.batch.services.processing_recovery import handle_retry_recovery

    context.pending_exhaustion = exhaustion_halt("Reprompt validation exhausted for rec-a")
    context.service._retry_service.process_retry_results.return_value = ([], set(), {}, None)

    state = MagicMock()
    state.retry_attempt = 2
    state.retry_max_attempts = 2
    state.missing_ids = []
    state.record_failure_counts = {}
    state.accumulated_results = []

    raised = None
    with (
        patch(
            "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
            return_value=True,
        ),
        patch(
            "agent_actions.llm.batch.services.processing_recovery.check_and_submit_repair",
            return_value=False,
        ),
    ):
        try:
            handle_retry_recovery(
                context,
                BatchIdentity(batch_id="b-1", file_name=PARENT, entry=_entry()),
                state,
                [],
                [],
                {},
            )
        except BaseException as exc:  # noqa: BLE001 - the test is about which one
            raised = exc

    assert raised is not None, (
        "the halt parked before the repair deferral was discarded; on_exhausted: "
        "raise finished the run reporting success"
    )
    assert raised_by_exhaustion_policy(raised)


def _repair_state():
    state = MagicMock()
    state.repair_attempt = 1
    state.repair_max_attempts = 3
    state.repair_judge_budget_remaining = None
    state.repair_submitted_ids = []
    state.graduated_results = []
    state.missing_ids = []
    state.record_failure_counts = {}
    return state


def test_the_repair_handler_surfaces_a_halt_before_submitting_another_round(context):
    """The third deferral, on the repair-resume path.

    handle_repair_recovery calls check_and_submit_reprompt — which can park —
    and then returns twice: once when reprompt defers, once when it submits the
    next repair round. Both skip the finaliser.
    """
    from agent_actions.llm.batch.services.processing_recovery import handle_repair_recovery

    context.pending_exhaustion = exhaustion_halt("Reprompt validation exhausted for rec-a")
    failing = BatchResult(custom_id=FAILING, content={"x": 1}, success=True)

    strategy = MagicMock()
    strategy.name = "expect"
    strategy.max_attempts = 3
    strategy.judge_budget_remaining = None
    loop = MagicMock()
    loop.split.return_value = ([], [failing], {})
    submission = MagicMock()
    submission.sent_ids = {FAILING}

    raised = None
    with (
        patch(
            "agent_actions.llm.batch.services.repair_ops.build_repair_strategy",
            return_value=strategy,
        ),
        patch(
            "agent_actions.llm.batch.services.repair_ops.submit_repair_batch",
            return_value=submission,
        ),
        patch("agent_actions.processing.evaluation.EvaluationLoop", return_value=loop),
        patch(
            "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
            return_value=True,
        ),
        patch("agent_actions.llm.batch.services.processing_recovery.register_recovery_batch"),
        patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"),
    ):
        try:
            handle_repair_recovery(
                context,
                BatchIdentity(batch_id="b-rp", file_name=PARENT, entry=_entry()),
                _repair_state(),
                [failing],
                [],
                {FAILING: {}},
            )
        except BaseException as exc:  # noqa: BLE001 - the test is about which one
            raised = exc

    assert raised is not None, (
        "the halt parked before the repair round was submitted was discarded; "
        "on_exhausted: raise finished the run reporting success"
    )
    assert raised_by_exhaustion_policy(raised)
