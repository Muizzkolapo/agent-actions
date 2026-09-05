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


def _state():
    state = MagicMock()
    state.retry_attempt = 1
    state.retry_max_attempts = 3
    state.missing_ids = [MISSING]
    state.record_failure_counts = {MISSING: 1}
    state.accumulated_results = []
    return state


def _context():
    context = MagicMock()
    context.action_name = ACTION
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
    context.service._retry_service.build_exhausted_recovery.side_effect = AssertionError(
        "retry attempt 1 of 3 was stamped as exhausted after a transient submit failure"
    )
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

    with patch(
        "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
        return_value=False,
    ):
        handle_retry_recovery(_context(), identity, _state(), [], [], {MISSING: {}})
