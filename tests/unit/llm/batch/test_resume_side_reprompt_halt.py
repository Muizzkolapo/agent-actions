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
    context.service._convert_batch_results_to_workflow_format.return_value = ([], MagicMock(), None)
    context.service._determine_output_path.return_value = "/tmp/out.json"
    context.service._retry_service.apply_exhausted_reprompt_metadata.return_value = exhaustion_halt(
        "Reprompt validation exhausted for rec-failing after 2 attempts"
    )
    return context


def test_the_resume_path_parks_the_halt_it_was_handed(context):
    failing = BatchResult(custom_id=FAILING, content=None, success=False, error="bad shape")
    loop, strategy = MagicMock(), MagicMock()
    strategy.name = "schema_check"
    loop.split.return_value = ([], [failing], {})

    with (
        patch(
            "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop",
            return_value=(loop, strategy),
        ),
        patch(
            "agent_actions.llm.batch.services.processing_recovery.cleanup_recovery",
            return_value=None,
        ),
        pytest.raises(RuntimeError) as halt,
    ):
        handle_reprompt_recovery(
            context,
            BatchIdentity(batch_id="b-rp", file_name=PARENT, entry=_entry()),
            _state(),
            [failing],
            [],
            {FAILING: {}},
        )

    # Parked during finalisation and raised after the write, still carrying the
    # policy tag. Drop the park and the halt disappears with no other symptom.
    assert raised_by_exhaustion_policy(halt.value)
    assert "exhausted" in str(halt.value).lower()
