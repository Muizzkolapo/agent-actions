"""`batch_preparation_concurrency` limits the batch actions of a step that prepare at once.

Each batch action of a step holds one input file's records while it prepares, so two of
them hold two (#1865). `--concurrency-limit` limits every action of the step, the online
actions beside them too. This key limits only the batch actions that prepare: an online
action still runs beside them, and a batch action that collects is not counted.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import WorkflowConfig
from agent_actions.workflow.executor import ActionExecutionResult, ExecutionMetrics
from agent_actions.workflow.parallel.action_executor import (
    ActionLevelOrchestrator,
    LevelExecutionParams,
)

CONFIGS = {
    "batch_a": {"dependencies": [], "run_mode": "batch", "model_vendor": "openai"},
    "batch_b": {"dependencies": [], "run_mode": "batch", "model_vendor": "openai"},
    "batch_c": {"dependencies": [], "run_mode": "batch", "model_vendor": "openai"},
    "online": {"dependencies": [], "run_mode": "online", "model_vendor": "openai"},
}


class _Executor:
    """Runs each action for a short while and records which actions ran together."""

    def __init__(self) -> None:
        self.running: set[str] = set()
        self.seen_together: list[frozenset[str]] = []

    async def execute_action_async(self, action: str, **_kwargs: Any) -> ActionExecutionResult:
        self.running.add(action)
        self.seen_together.append(frozenset(self.running))
        await asyncio.sleep(0.05)
        self.seen_together.append(frozenset(self.running))
        self.running.discard(action)
        return ActionExecutionResult(success=True, status="completed", metrics=ExecutionMetrics())

    def most_at_once(self, actions: set[str]) -> int:
        return max(len(together & actions) for together in self.seen_together)


def _run(
    actions: list[str],
    limit: int | None,
    submitted: frozenset[str] = frozenset(),
    concurrency_limit: int = 5,
) -> _Executor:
    executor = _Executor()
    state = MagicMock()
    state.is_completed.return_value = False
    state.get_pending_actions.return_value = actions
    state.is_batch_submitted.side_effect = lambda action: action in submitted
    state.get_batch_submitted_actions.return_value = []
    state.get_failed_actions.return_value = []
    orchestrator = ActionLevelOrchestrator(actions, {a: CONFIGS[a] for a in actions})
    asyncio.run(
        orchestrator.execute_level_async(
            LevelExecutionParams(
                level_idx=0,
                level_actions=actions,
                action_indices={a: i for i, a in enumerate(actions)},
                state_manager=state,
                action_executor=executor,
                total_steps=1,
                concurrency_limit=concurrency_limit,
                batch_preparation_concurrency=limit,
            )
        )
    )
    return executor


BATCH = {"batch_a", "batch_b", "batch_c"}


def test_without_the_key_the_batch_actions_prepare_together():
    executor = _run(["batch_a", "batch_b", "batch_c", "online"], limit=None)

    assert executor.most_at_once(BATCH) == 3


def test_the_key_limits_the_batch_actions_that_prepare_at_once():
    executor = _run(["batch_a", "batch_b", "batch_c", "online"], limit=2)

    assert executor.most_at_once(BATCH) == 2


def test_an_online_action_still_runs_beside_them():
    executor = _run(["batch_a", "batch_b", "batch_c", "online"], limit=1)

    assert executor.most_at_once(BATCH) == 1
    assert executor.most_at_once({"online", *BATCH}) == 2


def test_a_batch_action_waiting_its_turn_holds_no_slot_of_the_step():
    executor = _run(["batch_a", "batch_b", "online"], limit=1, concurrency_limit=2)

    assert any({"batch_a", "online"} <= together for together in executor.seen_together)


def test_a_batch_action_that_collects_is_not_counted():
    executor = _run(["batch_a", "batch_b", "online"], limit=1, submitted=frozenset({"batch_b"}))

    assert executor.most_at_once({"batch_a", "batch_b"}) == 2


VALID = {"name": "w", "description": "d", "actions": [{"name": "a", "intent": "i"}]}


def test_a_workflow_sets_it_at_its_top_level():
    workflow = WorkflowConfig.model_validate({**VALID, "batch_preparation_concurrency": 1})

    assert workflow.batch_preparation_concurrency == 1
    assert WorkflowConfig.model_validate(VALID).batch_preparation_concurrency is None


@pytest.mark.parametrize("value", [0, 51, "2", True, 1.5])
def test_a_value_that_is_not_a_count_of_1_to_50_is_refused(value):
    with pytest.raises(ValidationError, match="batch_preparation_concurrency"):
        WorkflowConfig.model_validate({**VALID, "batch_preparation_concurrency": value})
