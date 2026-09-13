"""Step boundaries must reach the event stream, not just the terminal.

A step's shape (which actions, how many in parallel, how long, what failed) is
the backbone of workflow progress. Written straight to a console it reaches one
consumer and never lands in ``events.json``; fired as an event every consumer
can read it and shape it.
"""

from __future__ import annotations

import asyncio
import io
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.core.manager import EventManager
from agent_actions.workflow.parallel.action_executor import (
    ActionLevelOrchestrator,
    LevelExecutionParams,
)


class _Capture:
    def __init__(self) -> None:
        self.events: list[BaseEvent] = []

    def accepts(self, event: BaseEvent) -> bool:
        return True

    def handle(self, event: BaseEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        pass


@pytest.fixture
def captured():
    EventManager.reset()
    manager = EventManager.get()
    manager.clear_handlers()
    capture = _Capture()
    manager.register(capture)
    yield capture
    EventManager.reset()


def _of_type(capture: _Capture, name: str) -> list[BaseEvent]:
    return [e for e in capture.events if e.event_type == name]


def _state_manager(*, pending: list[str], failed: list[str] | None = None) -> MagicMock:
    state = MagicMock()
    state.is_completed.return_value = False
    state.get_pending_actions.return_value = list(pending)
    state.get_batch_submitted_actions.return_value = []
    state.get_failed_actions.return_value = list(failed or [])
    state.is_completed_with_failures.return_value = False
    state.is_skipped.return_value = False
    return state


def _action_executor(failed: set[str] | None = None) -> MagicMock:
    failed = failed or set()

    async def execute(action, **kwargs):
        result = MagicMock()
        result.success = action not in failed
        result.status = "completed"
        result.output_folder = ""
        result.error = RuntimeError("boom") if action in failed else None
        result.metrics = None
        return result

    executor = MagicMock()
    executor.execute_action_async = execute
    return executor


def _run_level(orchestrator, *, level_idx, level_actions, pending, failed=None, indices=None):
    state = _state_manager(pending=pending, failed=failed)
    return asyncio.run(
        orchestrator.execute_level_async(
            LevelExecutionParams(
                level_idx=level_idx,
                level_actions=level_actions,
                action_indices=indices or {a: i for i, a in enumerate(level_actions)},
                state_manager=state,
                action_executor=_action_executor(set(failed or [])),
            )
        )
    )


def _orchestrator(actions: list[str], buf) -> ActionLevelOrchestrator:
    configs = {a: {"dependencies": []} for a in actions}
    return ActionLevelOrchestrator(
        actions, configs, console=Console(file=buf, highlight=False, no_color=True)
    )


class TestStepStart:
    def test_a_step_fires_a_start_event_naming_its_actions(self, captured):
        orch = _orchestrator(["a", "b"], io.StringIO())
        _run_level(orch, level_idx=0, level_actions=["a", "b"], pending=["a", "b"])

        starts = _of_type(captured, "StepStartEvent")
        assert len(starts) == 1
        assert starts[0].data["step_index"] == 0
        assert starts[0].data["pending"] == ["a", "b"]
        assert starts[0].data["actions"] == ["a", "b"]

    def test_a_fully_complete_step_still_fires_start_with_nothing_pending(self, captured):
        orch = _orchestrator(["a"], io.StringIO())
        _run_level(orch, level_idx=3, level_actions=["a"], pending=[])

        starts = _of_type(captured, "StepStartEvent")
        assert len(starts) == 1
        assert starts[0].data["step_index"] == 3
        assert starts[0].data["pending"] == []
        assert starts[0].data["actions"] == ["a"]


class TestStepComplete:
    def test_a_step_fires_a_complete_event_with_its_duration(self, captured):
        orch = _orchestrator(["a"], io.StringIO())
        _run_level(orch, level_idx=1, level_actions=["a"], pending=["a"])

        dones = _of_type(captured, "StepCompleteEvent")
        assert len(dones) == 1
        assert dones[0].data["step_index"] == 1
        assert dones[0].data["elapsed_time"] >= 0.0
        assert dones[0].data["failed"] == 0

    def test_a_failing_step_reports_its_failure_count_and_warns(self, captured):
        orch = _orchestrator(["a", "b"], io.StringIO())
        _run_level(orch, level_idx=2, level_actions=["a", "b"], pending=["a", "b"], failed=["b"])

        dones = _of_type(captured, "StepCompleteEvent")
        assert len(dones) == 1
        assert dones[0].data["failed"] == 1
        assert dones[0].level is EventLevel.WARN

    def test_a_fully_complete_step_still_fires_complete(self, captured):
        orch = _orchestrator(["a"], io.StringIO())
        _run_level(orch, level_idx=0, level_actions=["a"], pending=[])

        assert len(_of_type(captured, "StepCompleteEvent")) == 1


class TestConsoleIsNoLongerAProducer:
    """Step boundaries belong to the event stream; a direct print reaches only the terminal."""

    def test_running_a_step_writes_nothing_to_the_orchestrator_console(self, captured):
        buf = io.StringIO()
        orch = _orchestrator(["a", "b"], buf)
        _run_level(orch, level_idx=0, level_actions=["a", "b"], pending=["a", "b"])

        assert buf.getvalue() == ""

    def test_the_step_plan_is_not_dumped_up_front(self, captured):
        buf = io.StringIO()
        orch = _orchestrator(["a", "b", "c"], buf)
        assert not hasattr(orch, "log_execution_levels"), (
            "the up-front step plan duplicates what StepStartEvent carries per step"
        )


class TestSequentialPathFiresTheSameEvents:
    """Sequential and parallel runs are two producers of one progress stream."""

    @staticmethod
    def _workflow(execution_order, levels):
        from agent_actions.workflow.coordinator import AgentWorkflow
        from agent_actions.workflow.models import (
            CoreServices,
            SupportServices,
            WorkflowRuntimeConfig,
            WorkflowServices,
            WorkflowState,
        )

        wf = object.__new__(AgentWorkflow)
        metadata = MagicMock()
        metadata.agent_name = "wf"
        metadata.execution_order = execution_order
        metadata.action_indices = {n: i for i, n in enumerate(execution_order)}
        metadata.action_configs = {n: {"kind": "llm"} for n in execution_order}
        wf.metadata = metadata
        wf.config = MagicMock(spec=WorkflowRuntimeConfig)

        runtime = MagicMock()
        runtime.state = WorkflowState()
        runtime.console = Console(file=io.StringIO(), highlight=False, no_color=True)
        wf.runtime = runtime

        core = MagicMock(spec=CoreServices)
        core.state_manager = MagicMock()
        core.state_manager.is_completed.return_value = False
        core.state_manager.is_failed.return_value = False
        core.state_manager.is_completed_with_failures.return_value = False
        core.state_manager.is_skipped.return_value = False
        core.state_manager.is_workflow_complete.return_value = True
        core.state_manager.get_failed_actions.return_value = []
        core.action_executor = MagicMock()
        core.action_level_orchestrator = MagicMock()
        core.action_level_orchestrator.compute_execution_levels.return_value = levels
        wf.services = WorkflowServices(core=core, support=MagicMock(spec=SupportServices))
        wf.event_logger = MagicMock()
        wf.storage_backend = None
        return wf

    def test_each_level_fires_start_and_complete(self, captured):
        wf = self._workflow(["a", "b"], [["a"], ["b"]])
        wf._run_single_action = MagicMock(return_value=False)
        wf._run_storage_maintenance = MagicMock()

        wf._run_workflow_with_context(__import__("datetime").datetime.now())

        starts = _of_type(captured, "StepStartEvent")
        dones = _of_type(captured, "StepCompleteEvent")
        assert [e.data["step_index"] for e in starts] == [0, 1]
        assert [e.data["step_index"] for e in dones] == [0, 1]
        assert all(e.data["total_steps"] == 2 for e in starts)

    def test_the_sequential_console_carries_no_step_boundaries(self, captured):
        wf = self._workflow(["a"], [["a"]])
        wf._run_single_action = MagicMock(return_value=False)
        wf._run_storage_maintenance = MagicMock()

        wf._run_workflow_with_context(__import__("datetime").datetime.now())

        assert wf.runtime.console.file.getvalue() == ""
