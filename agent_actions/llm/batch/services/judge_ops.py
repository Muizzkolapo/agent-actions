"""A batch run's `llm_judge` calls, as a requester of side batches.

The suite runs exactly as it does online, against a judge cache filled from
batches. A step first runs it with an executor that holds each judge call back;
`side_batch` sends those and defers, and once they return their verdicts seed the
cache and the step runs again with every call a hit.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from agent_actions.expectations.judge import (
    BATCH_JUDGE_KEY,
    JUDGE_KIND,
    JudgeBudget,
    verdict_from_replies,
)
from agent_actions.llm.batch.services.side_batch import SideStep, register_side_requester
from agent_actions.llm.side_calls import HeldSideCalls, SideCall, SideReplies

if TYPE_CHECKING:
    from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
    from agent_actions.llm.providers.batch_base import BatchResult


def judges_in_batch(agent_config: dict[str, Any]) -> bool:
    """Whether this batch action's judge calls go out as a batch; ``judge_mode: online`` opts out."""
    expect = agent_config.get("expect")
    return isinstance(expect, dict) and expect.get("judge_mode") != "online"


def judge_verdicts(state: RecoveryState | None) -> dict[str, Any]:
    """Every verdict the file's judge batches returned, by verdict key: [passed, detail]."""
    return state.side_results.get(JUDGE_KIND, {}) if state else {}


def with_judge_results(agent_config: dict[str, Any], state: RecoveryState | None) -> dict[str, Any]:
    """*agent_config* carrying what the judge batches left, for a result writer that validates."""
    verdicts = judge_verdicts(state)
    if not verdicts:
        return agent_config
    return {
        **agent_config,
        BATCH_JUDGE_KEY: {
            "verdicts": verdicts,
            "budget_remaining": state.repair_judge_budget_remaining if state else None,
        },
    }


def collect_judgements(
    agent_config: dict[str, Any],
    results: list[BatchResult],
    *,
    verdicts: dict[str, Any],
    budget_remaining: int | None,
    context_map: dict[str, Any] | None = None,
) -> dict[str, SideCall]:
    """Run the suite over *results* as the next step will, holding back each judge call.

    A repair policy evaluates through the repair loop's strategy; ``repair: none``
    validates in the result writer, so its items are read the way the writer reads
    them. Only the judged rules run, so no other check is called twice, and on
    copies: an evaluation may put a verdict on a result. Each record is judged
    against the context its *context_map* row kept, as the next step judges it.
    """
    from agent_actions.expectations.service import create_expectation_service_from_config
    from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
    from agent_actions.llm.batch.processing.batch_result_strategy import (
        dispatch_results,
        validated_items,
    )
    from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
    from agent_actions.output.response.config_fields import get_default
    from agent_actions.processing.evaluation import EvaluationLoop
    from agent_actions.processing.evaluation.strategies import ExpectationStrategy

    held = HeldSideCalls()
    service = create_expectation_service_from_config(
        agent_config.get("expect"),
        action_name=agent_config.get("action_name") or agent_config.get("name", "unknown"),
        agent_config=agent_config,
        judge_budget_remaining=budget_remaining,
        judge_verdicts=verdicts,
        side_calls=held,
    )
    judged = [e for e in service.suite.expectations if e.type == "llm_judge"] if service else []
    if service is None or not judged:
        return {}
    # Rules are evaluated independently, so the judged ones alone make the same calls.
    service.suite = service.suite.model_copy(update={"expectations": judged})
    copies = [copy.copy(result) for result in results]
    if service.repair != "none":
        # The loop's own split would log placeholder verdicts as failures.
        strategy = ExpectationStrategy(service, BatchContextMetadata.judge_contexts(context_map))
        loop = EvaluationLoop(strategy)
        for result in copies:
            if not loop._is_already_graduated(result):
                strategy.evaluate(result)
    else:
        json_mode = agent_config.get("json_mode", get_default("json_mode"))
        output_field = agent_config.get("output_field", get_default("output_field"))
        for result in copies:
            if not BatchResultReconciler.is_answered(result):
                continue
            row = (context_map or {}).get(str(result.custom_id))
            for item in validated_items(
                result.content,
                json_mode=json_mode,
                output_field=output_field,
                dispatch=dispatch_results(agent_config, row),
            ):
                service.validate(item, BatchContextMetadata.get_judge_context(row))
    return dict(held.pending)


class JudgeRequester:
    """The `llm_judge` rules of an action's ``expect:`` block, judged in side batches."""

    kind = JUDGE_KIND

    def collect(self, step: SideStep) -> dict[str, SideCall]:
        if not judges_in_batch(step.agent_config):
            return {}
        return collect_judgements(
            step.agent_config,
            step.results,
            verdicts=step.settled(self.kind),
            budget_remaining=step.state.repair_judge_budget_remaining,
            context_map=step.context_map,
        )

    def sent(self, step: SideStep, calls: dict[str, SideCall]) -> None:
        """Charge the judge budget for the calls that went out, one per value."""
        before = JudgeBudget.at_start(
            step.agent_config.get("expect") or {}, step.state.repair_judge_budget_remaining
        )
        step.state.repair_judge_budget_remaining = None if before is None else before - len(calls)

    def settle(self, key: str, replies: SideReplies) -> list[Any]:
        return list(verdict_from_replies(replies))


register_side_requester(JudgeRequester())
