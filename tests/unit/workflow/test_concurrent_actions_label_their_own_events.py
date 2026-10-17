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


def test_each_judge_vote_on_a_worker_thread_is_logged_against_the_action(captured, monkeypatch):
    from agent_actions.expectations import judge

    def one_vote(agent_config, rule, value, **kwargs):
        _model_call("vote")
        return True, ""

    monkeypatch.setattr(judge, "invoke_judge", one_vote)

    with EventManager.get().context(action_name="judged", action_index=3):
        judge.invoke_judge_with_votes({}, "rule", "value", votes=3)

    calls = [event for event in captured if isinstance(event, LLMRequestEvent)]
    assert len(calls) == 3
    assert {(e.meta.extra.get("action_name"), e.data["action_name"]) for e in calls} == {
        ("judged", "judged")
    }


def test_an_event_told_its_action_keeps_it(captured):
    with EventManager.get().context(action_name="running"):
        fire_event(LLMRequestEvent(provider="p", action_name="named"))

    assert captured[-1].data["action_name"] == "named"


def test_an_event_outside_any_action_is_left_unnamed(captured):
    fire_event(LLMRequestEvent(provider="p"))

    assert captured[-1].data["action_name"] == ""
    assert "action_name" not in captured[-1].meta.extra
