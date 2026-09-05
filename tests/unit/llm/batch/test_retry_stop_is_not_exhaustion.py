"""A retry loop that stops early has not exhausted anything.

`submit_retry_batch` answers a transient failure with None. The loop then falls
through to the exhaustion branch with attempts still on the clock, and every
record it names is stamped as though the budget had run out — which the retry
`on_exhausted` policy later reads as grounds to halt the run.
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.processing_recovery import (
    BatchIdentity,
    handle_retry_recovery,
)

ACTION = "label_page"
PARENT = "pages.json"
MISSING = "rec-missing"


def _state(attempt: int = 1, max_attempts: int = 3):
    state = MagicMock()
    state.retry_attempt = attempt
    state.retry_max_attempts = max_attempts
    state.missing_ids = [MISSING]
    state.record_failure_counts = {MISSING: 1}
    state.accumulated_results = []
    return state


def _context():
    context = MagicMock()
    context.action_name = ACTION
    # A real RecoveryContext starts with nothing parked. Left as a MagicMock this
    # is truthy, so any guard that reads it tries to raise a mock.
    context.pending_exhaustion = None
    context.service._resolve_action_name.return_value = ACTION
    context.service._storage_backend = None
    # The transient failure: preparation or submission fell over and answered None.
    context.service._retry_service.process_retry_results.return_value = (
        [],
        {MISSING},
        {MISSING: 2},
        None,
    )
    context.service._retry_service.submit_retry_batch.return_value = None
    return context


def test_a_transient_submit_failure_does_not_stamp_exhaustion():
    entry = BatchJobEntry(
        batch_id="b-1",
        status="submitted",
        timestamp="2026-04-20T00:00:00Z",
        provider="openai",
        record_count=1,
        file_name=PARENT,
        parent_file_name=None,
        recovery_type="retry",
        recovery_attempt=1,
    )
    identity = BatchIdentity(batch_id="b-1", file_name=PARENT, entry=entry)
    seen = {}

    def _capture(context, identity, *, exhausted_recovery=None, **kwargs):
        seen["exhausted_recovery"] = exhausted_recovery
        return False

    with patch(
        "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
        side_effect=_capture,
    ):
        handle_retry_recovery(_context(), identity, _state(), [], [], {MISSING: {}})

    # The value the rest of the run reads. Marking the record exhausted here tells
    # the on_exhausted policy the budget is gone while two attempts remain.
    assert seen["exhausted_recovery"] is None


def test_the_records_are_not_carried_forward_as_exhausted():
    """Gating the local call is not enough — the id set travels too.

    The reprompt and repair finalisers rebuild exhaustion metadata from
    ``state.missing_ids``. Leaving the pre-round set on the state hands them the
    very records the guard just refused to exhaust.
    """
    entry = BatchJobEntry(
        batch_id="b-1",
        status="submitted",
        timestamp="2026-04-20T00:00:00Z",
        provider="openai",
        record_count=1,
        file_name=PARENT,
        parent_file_name=None,
        recovery_type="retry",
        recovery_attempt=1,
    )
    identity = BatchIdentity(batch_id="b-1", file_name=PARENT, entry=entry)
    state = _state()

    with patch(
        "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
        return_value=False,
    ):
        handle_retry_recovery(_context(), identity, state, [], [], {MISSING: {}})

    assert state.missing_ids == [], (
        "the retry state still names records the guard declined to exhaust; the "
        "reprompt and repair finalisers will rebuild the stamp from this set"
    )


def test_a_permanent_submission_failure_does_stamp_exhaustion():
    """The mirror: when no later pass can resend them, the loop has given up.

    A transient failure and an unrebuildable batch both used to answer None, so
    the caller could not tell "try again next pass" from "never".
    """
    from agent_actions.llm.batch.services.retry_ops import RetrySubmissionImpossible

    entry = BatchJobEntry(
        batch_id="b-1",
        status="submitted",
        timestamp="2026-04-20T00:00:00Z",
        provider="openai",
        record_count=1,
        file_name=PARENT,
        parent_file_name=None,
        recovery_type="retry",
        recovery_attempt=1,
    )
    identity = BatchIdentity(batch_id="b-1", file_name=PARENT, entry=entry)
    context = _context()
    context.service._retry_service.submit_retry_batch.side_effect = RetrySubmissionImpossible(
        "no records in context_map for 1 missing id(s)"
    )
    seen = {}

    def _capture(context, identity, *, exhausted_recovery=None, **kwargs):
        seen["exhausted_recovery"] = exhausted_recovery
        return False

    with patch(
        "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
        side_effect=_capture,
    ):
        handle_retry_recovery(context, identity, _state(), [], [], {MISSING: {}})

    context.service._retry_service.build_exhausted_recovery.assert_called_once()
    assert seen["exhausted_recovery"] is not None


def test_the_last_attempt_before_the_budget_is_still_not_exhaustion():
    """The boundary the other cases miss.

    At attempt max-1 the submit gate still fires, so a transient failure lands in
    the same branch with one attempt left. A guard written `>= max - 1` passes
    every other test here and re-introduces the bug one round later.
    """
    entry = BatchJobEntry(
        batch_id="b-1",
        status="submitted",
        timestamp="2026-04-20T00:00:00Z",
        provider="openai",
        record_count=1,
        file_name=PARENT,
        parent_file_name=None,
        recovery_type="retry",
        recovery_attempt=2,
    )
    identity = BatchIdentity(batch_id="b-1", file_name=PARENT, entry=entry)
    context = _context()
    state = _state(attempt=2, max_attempts=3)
    seen = {}

    def _capture(context, identity, *, exhausted_recovery=None, **kwargs):
        seen["exhausted_recovery"] = exhausted_recovery
        return False

    with patch(
        "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
        side_effect=_capture,
    ):
        handle_retry_recovery(context, identity, state, [], [], {MISSING: {}})

    context.service._retry_service.build_exhausted_recovery.assert_not_called()
    assert seen["exhausted_recovery"] is None
    # Both halves, at the boundary: withholding the stamp is not enough while the
    # id set the finalisers rebuild from still names the record.
    assert state.missing_ids == []


def test_the_exhausted_branch_keeps_the_id_set_it_stamped():
    """The mirror of the clear: clearing unconditionally is just as wrong.

    The finalisers rebuild retry exhaustion from missing_ids. Clearing it on the
    branch that *did* exhaust drops the retry metadata from every record that
    spent its attempts, which is the same loss in the other direction.
    """
    entry = BatchJobEntry(
        batch_id="b-1",
        status="submitted",
        timestamp="2026-04-20T00:00:00Z",
        provider="openai",
        record_count=1,
        file_name=PARENT,
        parent_file_name=None,
        recovery_type="retry",
        recovery_attempt=3,
    )
    identity = BatchIdentity(batch_id="b-1", file_name=PARENT, entry=entry)
    context = _context()
    context.service._retry_service.build_exhausted_recovery.side_effect = None
    context.service._retry_service.build_exhausted_recovery.return_value = {MISSING: object()}
    state = _state(attempt=3, max_attempts=3)
    seen = {}

    def _capture(context, identity, *, exhausted_recovery=None, **kwargs):
        seen["exhausted_recovery"] = exhausted_recovery
        return False

    with patch(
        "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
        side_effect=_capture,
    ):
        handle_retry_recovery(context, identity, state, [], [], {MISSING: {}})

    assert seen["exhausted_recovery"], "the budget was spent but nothing was stamped exhausted"
    assert state.missing_ids == [MISSING], (
        "the exhausted branch cleared the id set the finalisers rebuild from; "
        "every record that spent its attempts loses its retry metadata"
    )
