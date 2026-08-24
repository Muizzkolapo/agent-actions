"""Which records a repair round owns, and when it stops owning them.

The loop defers when a round is already regenerating these records, so a resume
of the never-retired original batch cannot buy a second generation of each. That
was a whole-file question — "is any repair round outstanding" — which is too
coarse in two directions:

* it blocks a record no round ever held, and
* it never releases, because a round that has already come back still counts;
  its ids sit in `repair_submitted_ids` until the next round overwrites them.

The second is what sent the reprompt chain's output to the bin: every
continuation after a round returned saw the round as still outstanding.

Ownership is per record, and it ends when the round's results are in hand.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import RecoveryPhase
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.providers.batch_base import BatchResult

from .test_reprompt_feedback_delivery import RecordingProvider

ACTION = "author"
FAILING = {"options": ["only-one"]}


def _agent_config(**expect: Any) -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "agent_type": ACTION,
        "json_mode": False,
        "model_name": "test-model",
        "prompt": "Write the options.",
        "run_mode": "batch",
        "expect": {
            "repair": "auto",
            "max_iterations": 4,
            "on_exhausted": "return_last",
            "expectations": [{"id": "enough", "type": "item_count", "field": "options", "min": 2}],
            **expect,
        },
    }


def _context_map(*ids: str) -> dict[str, Any]:
    return {
        cid: {"target_id": cid, "source_guid": f"sg-{cid}", "content": {"source": {"t": cid}}}
        for cid in ids
    }


def _re_enter(failing_ids: list[str], owned_by_a_round: list[str]):
    """The original-batch re-entry, with a round already out for *owned*."""
    state = RecoveryState(
        phase=RecoveryPhase.REPAIR,
        repair_attempt=1,
        repair_max_attempts=3,
        repair_submitted_ids=list(owned_by_a_round),
        evaluation_strategy_name="expectations",
    )
    provider = RecordingProvider()
    context = MagicMock()
    context.agent_config = _agent_config()
    context.provider = provider
    context.pending_exhaustion = None
    context.service._resolve_action_name.return_value = ACTION
    context.service._storage_backend = None
    context.service._action_indices = {ACTION: 0}
    context.service._dependency_configs = {}
    with (
        patch.object(pr.RecoveryStateManager, "load", return_value=state),
        patch.object(pr.RecoveryStateManager, "save"),
        patch.object(pr, "register_recovery_batch"),
        patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare",
            return_value=MagicMock(formatted_prompt="p", llm_context={}, should_execute=True),
        ),
    ):
        should_continue = pr.check_and_submit_repair(
            context,
            MagicMock(file_name="f.json"),
            batch_results=[
                BatchResult(custom_id=cid, content=dict(FAILING), success=True)
                for cid in failing_ids
            ],
            context_map=_context_map(*failing_ids),
            recovery_state=None,
        )
    return should_continue, provider.submitted


class TestARoundOwnsOnlyTheRecordsItHolds:
    def test_a_record_a_round_is_regenerating_is_not_resubmitted(self):
        should_continue, submitted = _re_enter(["r1"], owned_by_a_round=["r1"])
        assert submitted == [], "a second generation was bought for a record already out"
        assert should_continue is False, "the pass must defer to the round that holds it"

    def test_a_record_no_round_holds_is_not_blocked_by_one(self):
        """Too coarse before: any outstanding round froze every other record."""
        _sc, submitted = _re_enter(["r2"], owned_by_a_round=["r1"])
        ids = [t["custom_id"] for t in submitted]
        assert ids == ["r2"], (
            f"r2 was held up by a round that never held it ({ids}); its repair never starts"
        )

    def test_nothing_outstanding_submits_normally(self):
        _sc, submitted = _re_enter(["r1"], owned_by_a_round=[])
        assert [t["custom_id"] for t in submitted] == ["r1"]


class TestOwnershipEndsWhenTheResultsAreInHand:
    def test_a_returned_round_no_longer_holds_its_records(self):
        """Otherwise every continuation after it defers, forever."""
        state = RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=3,
            repair_submitted_ids=["r1"],
            evaluation_strategy_name="expectations",
        )
        context = MagicMock()
        context.agent_config = _agent_config(max_iterations=1)
        context.pending_exhaustion = None
        context.service._resolve_action_name.return_value = ACTION
        context.service._storage_backend = None
        context.service._retry_service.build_exhausted_recovery.return_value = None
        with patch.object(pr, "_finalize_and_cleanup", return_value="/out.json"):
            pr.handle_repair_recovery(
                context,
                MagicMock(file_name="f.json"),
                state,
                recovery_results=[BatchResult(custom_id="r1", content=dict(FAILING), success=True)],
                accumulated=[],
                context_map=_context_map("r1"),
            )
        assert state.repair_submitted_ids == [], (
            f"the round came back but still claims {state.repair_submitted_ids}; every later "
            "continuation reads that as a round still running and defers"
        )
