"""A parallel step labels a tool or hitl action under batch as online in its events."""

import pytest

from agent_actions.logging.core.manager import EventManager
from agent_actions.logging.events import ActionCompleteEvent, ActionStartEvent
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator


class _Result:
    success = True
    output_folder = None
    error = None
    status = "completed"
    metrics = None


class _Executor:
    async def execute_action_async(self, action, **kwargs):
        return _Result()


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "mode"),
    [
        ({"kind": "tool", "model_vendor": "tool", "run_mode": "batch"}, "online"),
        ({"kind": "hitl", "model_vendor": "hitl", "run_mode": "batch"}, "online"),
        ({"kind": "llm", "model_vendor": "openai", "run_mode": "batch"}, "batch"),
    ],
)
async def test_start_and_complete_events_carry_the_mode_the_action_runs_in(captured, config, mode):
    orchestrator = ActionLevelOrchestrator(
        execution_order=["only"], action_configs={"only": config}
    )

    await orchestrator._execute_single_action("only", {"only": 0}, _Executor())

    modes = {
        type(event).__name__: event.mode
        for event in captured
        if isinstance(event, ActionStartEvent | ActionCompleteEvent)
    }
    assert modes == {"ActionStartEvent": mode, "ActionCompleteEvent": mode}
