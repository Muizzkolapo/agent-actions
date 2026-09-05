"""A reprompt round must not drop the bookkeeping other loops put in the state.

`carry_forward` exists because finalisation rebuilds `exhausted_recovery` from
the retry bookkeeping, so a repair round that replaced the state would drop a
record's retry-exhaustion metadata purely because a repair happened. The reprompt
round builds a fresh `RecoveryState` and had the same hole: `missing_ids`,
`record_failure_counts` and `validation_status` were dropped, and so was
everything the repair loop had recorded.
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import RecoveryPhase
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.providers.batch_base import BatchResult

ACTION = "author"


def _prior() -> RecoveryState:
    return RecoveryState(
        phase=RecoveryPhase.REPAIR,
        missing_ids=["gone-1", "gone-2"],
        record_failure_counts={"gone-1": 3, "gone-2": 3},
        validation_status={"r1": "checked"},
        retry_attempt=3,
        retry_max_attempts=3,
        repair_attempt=2,
        repair_max_attempts=3,
        repair_submitted_ids=["out-for-repair"],
        repair_judge_budget_remaining=7,
        evaluation_strategy_name="expectations",
    )


def _state_after_a_reprompt_round(prior: RecoveryState) -> RecoveryState:
    failing = BatchResult(custom_id="r1", content={"a": 1}, success=True)
    loop = MagicMock()
    loop.split.return_value = ([], [failing], {})
    strategy = MagicMock()
    strategy.name = "check_it"
    strategy.max_attempts = 2
    strategy.on_exhausted = "return_last"

    context = MagicMock()
    context.agent_config = {
        "name": ACTION,
        "action_name": ACTION,
        "reprompt": {"validation": "check_it", "max_attempts": 2},
    }
    context.service._resolve_action_name.return_value = ACTION
    context.service._storage_backend = None
    context.service._retry_service.submit_reprompt_batch.side_effect = lambda **kw: (
        "b-rp",
        {r.custom_id for r in kw["failed_results"]},
    )
    saved: list[RecoveryState] = []
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


class TestTheRetryBookkeepingSurvives:
    def test_the_records_retry_gave_up_on_are_still_named(self):
        state = _state_after_a_reprompt_round(_prior())
        assert state.missing_ids == ["gone-1", "gone-2"], (
            f"missing_ids became {state.missing_ids}; finalisation rebuilds exhausted_recovery "
            "from these, so those records ship with no retry metadata"
        )

    def test_their_failure_counts_survive(self):
        state = _state_after_a_reprompt_round(_prior())
        assert state.record_failure_counts == {"gone-1": 3, "gone-2": 3}

    def test_the_validation_status_survives(self):
        state = _state_after_a_reprompt_round(_prior())
        assert state.validation_status == {"r1": "checked"}


class TestTheRepairBookkeepingSurvives:
    def test_the_round_counter_survives(self):
        state = _state_after_a_reprompt_round(_prior())
        assert state.repair_attempt == 2, (
            f"the repair counter reset to {state.repair_attempt}; the loop starts its rounds "
            "again from zero and never reaches max_iterations"
        )
        assert state.repair_max_attempts == 3

    def test_the_judge_budget_survives(self):
        state = _state_after_a_reprompt_round(_prior())
        assert state.repair_judge_budget_remaining == 7, (
            "the budget reset, so the cap bounds a round instead of the run"
        )

    def test_what_repair_still_holds_survives(self):
        state = _state_after_a_reprompt_round(_prior())
        assert state.repair_submitted_ids == ["out-for-repair"]


class TestAFirstRepromptIsUnaffected:
    def test_no_prior_state_means_the_defaults(self):
        state = _state_after_a_reprompt_round(None)
        assert state.missing_ids == []
        assert state.record_failure_counts == {}
        assert state.repair_attempt == 0
        assert state.repair_submitted_ids == []
