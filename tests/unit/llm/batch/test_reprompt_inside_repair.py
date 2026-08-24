"""Online nests reprompt inside every repair iteration; batch must too.

Online's repair loop calls `generate()` each iteration and reprompt lives inside
it, so output that does not match the schema is regenerated with that feedback
before the suite judges it. Batch sent a repair round's results straight to the
suite: schema-invalid output became a structural failure instead of being
repaired, burning a repair iteration and a judge call on exactly the problem
reprompt exists to fix.

In batch a reprompt round is its own deferred batch, so the nesting is: the
repair round returns, the reprompt check runs on those results and may defer,
and `handle_reprompt_recovery` resumes into the repair loop on the way back.

A first attempt at this was reverted because that resumption never happened —
the deferral asked a whole-file question and a round whose results were already
in hand still counted as running, so every continuation deferred and the
regenerated output was dropped without being persisted. Ownership is per record
now and ends on return, which is what makes the resumption reachable. The
delivery test below is the one that failed then.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import BatchStatus, RecoveryPhase, RecoveryType
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.providers.batch_base import BatchResult

ACTION = "author"
FAILING = {"options": ["one"]}
PASSING = {"options": ["a", "b"]}


def _agent_config(**expect: Any) -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "agent_type": ACTION,
        "json_mode": False,
        "model_name": "test-model",
        "prompt": "Write the options.",
        "expect": {
            "repair": "auto",
            "max_iterations": 3,
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


def _returned_round(reprompt_defers: bool, content: dict[str, Any]):
    """Drive a repair round coming back; report what happened."""
    state = RecoveryState(
        phase=RecoveryPhase.REPAIR,
        repair_attempt=1,
        repair_max_attempts=3,
        repair_submitted_ids=["r1"],
        evaluation_strategy_name="expectations",
    )
    context = MagicMock()
    context.agent_config = _agent_config()
    context.pending_exhaustion = None
    context.provider.submit_batch.return_value = ("b-repair-2", "submitted")
    context.service._resolve_action_name.return_value = ACTION
    context.service._storage_backend = None
    context.service._action_indices = {ACTION: 0}
    context.service._dependency_configs = {}
    context.service._retry_service.build_exhausted_recovery.return_value = None
    with (
        patch.object(
            pr, "check_and_submit_reprompt", return_value=not reprompt_defers
        ) as reprompt_check,
        patch.object(pr, "_finalize_and_cleanup", return_value="/out.json") as finalize,
        patch(
            "agent_actions.llm.batch.services.repair_ops.submit_repair_batch",
            return_value=None,
        ) as repair_submit,
        patch.object(pr.RecoveryStateManager, "save"),
        patch.object(pr, "register_recovery_batch"),
        patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare",
            return_value=MagicMock(formatted_prompt="p", llm_context={}, should_execute=True),
        ),
    ):
        returned = pr.handle_repair_recovery(
            context,
            MagicMock(file_name="f.json"),
            state,
            recovery_results=[BatchResult(custom_id="r1", content=dict(content), success=True)],
            accumulated=[],
            context_map=_context_map("r1"),
        )
    return returned, reprompt_check, finalize, repair_submit


class TestARepairRoundIsRepromptedBeforeItIsJudged:
    def test_the_returned_round_is_offered_to_reprompt(self):
        _p, reprompt_check, _f, _rs = _returned_round(reprompt_defers=False, content=PASSING)
        assert reprompt_check.call_count == 1, (
            "the repair round's output went straight to the suite; schema-invalid output is "
            "judged as a structural failure instead of being regenerated"
        )

    def test_it_is_the_returned_results_that_are_offered(self):
        _p, reprompt_check, _f, _rs = _returned_round(reprompt_defers=False, content=PASSING)
        offered = reprompt_check.call_args.kwargs["batch_results"]
        assert [r.custom_id for r in offered] == ["r1"]

    def test_a_reprompt_round_defers_the_repair_evaluation(self):
        path, _rc, finalize, repair_submit = _returned_round(reprompt_defers=True, content=FAILING)
        assert path is None, "the pass finalised while a reprompt round was in flight"
        assert finalize.call_count == 0
        assert repair_submit.call_count == 0, (
            "the deferral came from starting another repair round, not from the reprompt round — "
            "the record was sent back to the model without its schema being repaired first"
        )

    def test_nothing_to_reprompt_lets_the_suite_judge(self):
        path, _rc, finalize, repair_submit = _returned_round(reprompt_defers=False, content=PASSING)
        assert path == "/out.json"
        assert finalize.call_count == 1


class TestTheRegeneratedOutputActuallyReachesTheFile:
    """The property the first attempt got wrong, asserted directly."""

    def test_a_continuation_after_the_round_returned_is_not_deferred(self):
        entry = BatchJobEntry(
            batch_id="b-repair-1",
            status=BatchStatus.SUBMITTED,  # never updated until finalisation
            timestamp="t",
            provider="p",
            file_name="f.json_repair_1",
            parent_file_name="f.json",
            recovery_type=RecoveryType.REPAIR,
            recovery_attempt=1,
        )
        # The round came back, so it no longer holds anything.
        state = RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=1,
            repair_submitted_ids=[],
            evaluation_strategy_name="expectations",
        )
        context = MagicMock()
        context.agent_config = _agent_config(max_iterations=1)
        context.pending_exhaustion = None
        context.provider.check_status.return_value = BatchStatus.COMPLETED
        context.manager.get_all_jobs.return_value = {"f.json_repair_1": entry}
        context.service._resolve_action_name.return_value = ACTION
        context.service._storage_backend = None

        reprompted = BatchResult(custom_id="r1", content=dict(PASSING), success=True)
        should_continue = pr.check_and_submit_repair(
            context,
            MagicMock(file_name="f.json"),
            batch_results=[reprompted],
            context_map=_context_map("r1"),
            recovery_state=state,
        )
        assert should_continue is True, (
            "the reprompt chain's output was deferred and dropped without being persisted — the "
            "round had already come back, so nothing was actually in flight"
        )
