"""Online nests reprompt inside every repair iteration; batch must too.

Online's repair loop calls `generate()` each iteration, and reprompt lives
inside it — so a repair round whose output does not match the schema is
regenerated with that feedback before the suite ever judges it, and each
iteration gets a fresh reprompt budget.

Batch sent a repair round's results straight to the suite. Schema-invalid output
was judged as a structural failure instead of being repaired, burning a repair
iteration on a problem reprompt exists to fix.

In batch a reprompt round is itself a deferred batch, so nesting means: the
repair round returns, the reprompt check runs on those results and may defer,
and the reprompt handler resumes into the repair loop on its way back.
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import RecoveryPhase
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services import processing_recovery as pr

ACTION = "author"


def _repair_state() -> RecoveryState:
    return RecoveryState(
        phase=RecoveryPhase.REPAIR,
        repair_attempt=2,
        repair_max_attempts=3,
        repair_submitted_ids=["r1"],
        repair_judge_budget_remaining=7,
        reprompt_attempt=1,
        reprompt_max_attempts=2,
        evaluation_strategy_name="expectations",
    )


class TestARepromptRoundKeepsTheRepairBookkeeping:
    """Without this the repair counter resets and the loop never terminates."""

    def _reprompt_state_built_from(self, prior: RecoveryState) -> RecoveryState:
        saved: list[RecoveryState] = []
        context = MagicMock()
        context.service._resolve_action_name.return_value = ACTION
        context.service._storage_backend = None
        context.service._retry_service.submit_reprompt_batch.return_value = ("b-rp", 1)
        context.agent_config = {
            "name": ACTION,
            "action_name": ACTION,
            "reprompt": {"validation": "check_it", "max_attempts": 2},
        }
        from agent_actions.llm.providers.batch_base import BatchResult

        failing = BatchResult(custom_id="r1", content={"a": 1}, success=True)
        loop = MagicMock()
        loop.split.return_value = ([], [failing], {})
        strategy = MagicMock()
        strategy.name = "check_it"
        strategy.max_attempts = 2
        strategy.on_exhausted = "return_last"
        with (
            patch(
                "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop",
                return_value=(loop, strategy),
            ),
            patch.object(
                pr.RecoveryStateManager, "save", side_effect=lambda *a, **k: saved.append(a[-1])
            ),
            patch.object(pr, "register_recovery_batch"),
        ):
            pr.check_and_submit_reprompt(
                context,
                MagicMock(file_name="f.json"),
                batch_results=[failing],
                context_map={"r1": {"target_id": "r1", "source_guid": "sg-r1", "content": {}}},
                recovery_state=prior,
            )
        assert saved, "the reprompt round did not persist state"
        return saved[-1]

    def test_the_repair_counter_survives(self):
        state = self._reprompt_state_built_from(_repair_state())
        assert state.repair_attempt == 2, (
            f"the repair counter reset to {state.repair_attempt}; the loop would start its rounds "
            "again from zero and never reach max_iterations"
        )
        assert state.repair_max_attempts == 3

    def test_the_judge_budget_survives(self):
        state = self._reprompt_state_built_from(_repair_state())
        assert state.repair_judge_budget_remaining == 7, (
            "the judge budget reset, so each nested reprompt would hand the loop a full budget "
            "again and the cap would bound a round instead of the run"
        )

    def test_the_ids_in_flight_survive(self):
        state = self._reprompt_state_built_from(_repair_state())
        assert state.repair_submitted_ids == ["r1"]

    def test_a_first_reprompt_with_no_prior_repair_is_unaffected(self):
        state = self._reprompt_state_built_from(
            RecoveryState(phase=RecoveryPhase.RETRY, evaluation_strategy_name="validation")
        )
        assert state.repair_attempt == 0
        assert state.repair_submitted_ids == []


class TestARepairRoundIsRepromptedBeforeItIsJudged:
    """The nesting itself: reprompt gets a look before the suite does."""

    def _repair_round_returns(self, needs_reprompt: bool, passes: bool = False):
        from agent_actions.llm.batch.core.batch_models import BatchIdentity, BatchJobEntry
        from agent_actions.llm.providers.batch_base import BatchResult

        options = ["a", "b"] if passes else ["one"]
        returned = [BatchResult(custom_id="r1", content={"options": options}, success=True)]
        context = MagicMock()
        context.service._resolve_action_name.return_value = ACTION
        context.service._storage_backend = None
        context.service._retry_service.build_exhausted_recovery.return_value = None
        context.agent_config = {
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
                "expectations": [
                    {"id": "enough", "type": "item_count", "field": "options", "min": 2}
                ],
            },
        }
        context.pending_exhaustion = None
        context.provider.submit_batch.return_value = ("b-repair-2", "submitted")
        identity = BatchIdentity(
            batch_id="b-1",
            file_name="f.json",
            entry=BatchJobEntry(
                batch_id="b-1", status="completed", timestamp="t", provider="p", file_name="f.json"
            ),
        )
        state = RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=3,
            repair_submitted_ids=["r1"],
            evaluation_strategy_name="expectations",
        )
        with (
            patch.object(
                pr, "check_and_submit_reprompt", return_value=not needs_reprompt
            ) as reprompt_check,
            patch.object(pr, "_finalize_and_cleanup", return_value="/out.json") as finalize,
            patch.object(pr.RecoveryStateManager, "save"),
            patch.object(pr, "register_recovery_batch"),
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=MagicMock(formatted_prompt="p", llm_context={}, should_execute=True),
            ),
        ):
            returned_path = pr.handle_repair_recovery(
                context,
                identity,
                state,
                recovery_results=returned,
                accumulated=[],
                context_map={"r1": {"target_id": "r1", "source_guid": "sg-r1", "content": {}}},
            )
        return returned_path, reprompt_check, finalize

    def test_the_returned_round_is_offered_to_reprompt(self):
        _path, reprompt_check, _finalize = self._repair_round_returns(needs_reprompt=False)
        assert reprompt_check.call_count == 1, (
            "the repair round's output went straight to the suite; schema-invalid output is judged "
            "as a structural failure instead of being regenerated, burning a repair iteration"
        )

    def test_it_is_the_returned_results_that_are_offered(self):
        _path, reprompt_check, _finalize = self._repair_round_returns(needs_reprompt=False)
        offered = reprompt_check.call_args.kwargs["batch_results"]
        assert [r.custom_id for r in offered] == ["r1"]

    def test_a_reprompt_round_defers_the_repair_evaluation(self):
        path, _reprompt_check, finalize = self._repair_round_returns(needs_reprompt=True)
        assert path is None, "the pass finalised while a reprompt round was in flight"
        assert finalize.call_count == 0

    def test_nothing_to_reprompt_lets_the_suite_judge(self):
        """Reprompt passes it through, the suite finds it good, the file is written."""
        path, _reprompt_check, finalize = self._repair_round_returns(
            needs_reprompt=False, passes=True
        )
        assert path == "/out.json"
        assert finalize.call_count == 1

    def test_a_record_the_suite_still_rejects_gets_another_round(self):
        path, _reprompt_check, finalize = self._repair_round_returns(needs_reprompt=False)
        assert path is None, "the loop had rounds left and should have used one"
        assert finalize.call_count == 0
