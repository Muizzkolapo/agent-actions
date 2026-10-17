"""Actions running at once each label their own events with their name and index.

The interleaving is forced, not hoped for: one action waits mid-flight until the
other has fired, so a single shared "current action" would mislabel one of them.
Events fire from a worker thread too, as a provider call under `asyncio.to_thread` does.
"""

import asyncio
from dataclasses import dataclass

import pytest

from agent_actions.logging.core.manager import EventManager, fire_event
from agent_actions.logging.events import LLMRequestEvent
from agent_actions.workflow.parallel.action_executor import (
    ActionLevelOrchestrator,
    ParallelExecutionParams,
)


@dataclass
class _Result:
    success: bool = True
    output_folder: str | None = None
    error: Exception | None = None
    status: str = "completed"
    metrics: None = None


class _Capture:
    def __init__(self):
        self.events = []

    def accepts(self, event):
        return True

    def handle(self, event):
        self.events.append(event)

    def flush(self):
        pass


@pytest.fixture
def captured():
    EventManager.reset()
    capture = _Capture()
    EventManager.get().register(capture)
    yield capture.events
    EventManager.reset()


def _model_call(provider: str) -> None:
    fire_event(LLMRequestEvent(provider=provider, model="m"))


class _InterleavingExecutor:
    """`first` fires, waits until `second` has fired, then fires again."""

    def __init__(self):
        self.second_fired = asyncio.Event()

    async def execute_action_async(self, action, **kwargs):
        if action == "first":
            await asyncio.to_thread(_model_call, "first-before")
            await self.second_fired.wait()
            await asyncio.to_thread(_model_call, "first-after")
        else:
            await asyncio.to_thread(_model_call, "second")
            self.second_fired.set()
        return _Result()


def _labels(events):
    return {
        event.data["provider"]: (
            event.meta.extra.get("action_name"),
            event.meta.extra.get("action_index"),
            event.data["action_name"],
        )
        for event in events
        if isinstance(event, LLMRequestEvent)
    }


@pytest.mark.asyncio
async def test_two_actions_in_flight_each_label_their_own_model_calls(captured):
    actions = ["first", "second"]
    orchestrator = ActionLevelOrchestrator(
        execution_order=actions, action_configs={a: {"run_mode": "online"} for a in actions}
    )

    await orchestrator._execute_parallel_actions(
        ParallelExecutionParams(
            pending_actions=actions,
            action_indices={"first": 0, "second": 1},
            action_executor=_InterleavingExecutor(),
            concurrency_limit=5,
            level_idx=0,
        )
    )

    assert _labels(captured) == {
        "first-before": ("first", 0, "first"),
        "second": ("second", 1, "second"),
        "first-after": ("first", 0, "first"),
    }


@pytest.mark.asyncio
async def test_a_lone_action_of_a_step_labels_its_model_calls(captured):
    class _Executor:
        async def execute_action_async(self, action, **kwargs):
            await asyncio.to_thread(_model_call, action)
            return _Result()

    orchestrator = ActionLevelOrchestrator(
        execution_order=["before", "only"],
        action_configs={"before": {}, "only": {"run_mode": "online"}},
    )

    await orchestrator._execute_single_action("only", {"before": 0, "only": 1}, _Executor())

    assert _labels(captured) == {"only": ("only", 1, "only")}
