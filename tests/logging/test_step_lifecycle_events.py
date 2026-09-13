"""Step boundaries must reach the event stream, not just the terminal.

A step's shape (which actions, how many in parallel, how long, what failed) is
the backbone of workflow progress. Written straight to a console it reaches one
consumer and never lands in ``events.json``; fired as an event every consumer
can read it and shape it.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.core.manager import EventManager
from agent_actions.workflow.execution_events import (
    WorkflowEventLogger,
    fire_step_complete,
    fire_step_start,
)
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


def _state_manager(
    *,
    pending: list[str],
    failed: list[str] | None = None,
    partial: list[str] | None = None,
    skipped: list[str] | None = None,
    completed: list[str] | None = None,
    batch: list[str] | None = None,
) -> MagicMock:
    failed, partial = list(failed or []), list(partial or [])
    skipped, batch = list(skipped or []), list(batch or [])
    done = list(completed or []) + partial

    state = MagicMock()
    state.get_pending_actions.return_value = list(pending)
    state.get_batch_submitted_actions.return_value = batch
    state.get_failed_actions.side_effect = lambda actions: [a for a in actions if a in failed]
    state.is_completed.side_effect = lambda a: a in done
    state.is_completed_with_failures.side_effect = lambda a: a in partial
    state.is_skipped.side_effect = lambda a: a in skipped
    return state


def _action_executor(failed: set[str] | None = None, takes: float = 0.0) -> MagicMock:
    failed = failed or set()

    async def execute(action, **kwargs):
        if takes:
            await asyncio.sleep(takes)
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


def _run_level(
    orchestrator,
    *,
    level_idx,
    level_actions,
    pending,
    failed=None,
    indices=None,
    total_steps=4,
    takes=0.0,
    **state_kwargs,
):
    state = _state_manager(pending=pending, failed=failed, **state_kwargs)
    return asyncio.run(
        orchestrator.execute_level_async(
            LevelExecutionParams(
                level_idx=level_idx,
                level_actions=level_actions,
                action_indices=indices or {a: i for i, a in enumerate(level_actions)},
                state_manager=state,
                action_executor=_action_executor(set(failed or []), takes=takes),
                total_steps=total_steps,
            )
        )
    )


def _orchestrator(actions: list[str]) -> ActionLevelOrchestrator:
    return ActionLevelOrchestrator(actions, {a: {"dependencies": []} for a in actions})


class TestStepStart:
    def test_a_step_fires_a_start_event_naming_its_actions(self, captured):
        orch = _orchestrator(["a", "b"])
        _run_level(orch, level_idx=0, level_actions=["a", "b"], pending=["a", "b"])

        starts = _of_type(captured, "StepStartEvent")
        assert len(starts) == 1
        assert starts[0].data["step_index"] == 0
        assert starts[0].data["pending"] == ["a", "b"]
        assert starts[0].data["actions"] == ["a", "b"]

    def test_a_fully_complete_step_still_fires_start_with_nothing_pending(self, captured):
        orch = _orchestrator(["a"])
        _run_level(orch, level_idx=3, level_actions=["a"], pending=[])

        starts = _of_type(captured, "StepStartEvent")
        assert len(starts) == 1
        assert starts[0].data["step_index"] == 3
        assert starts[0].data["pending"] == []
        assert starts[0].data["actions"] == ["a"]


class TestStepComplete:
    def test_a_step_fires_a_complete_event_with_its_duration(self, captured):
        orch = _orchestrator(["a"])
        _run_level(orch, level_idx=1, level_actions=["a"], pending=["a"], completed=["a"])

        dones = _of_type(captured, "StepCompleteEvent")
        assert len(dones) == 1
        assert dones[0].data["step_index"] == 1
        assert dones[0].data["failed"] == 0
        assert "complete in" in dones[0].message

    def test_the_duration_is_the_time_the_step_actually_took(self, captured):
        orch = _orchestrator(["a"])
        _run_level(
            orch, level_idx=0, level_actions=["a"], pending=["a"], takes=0.05, completed=["a"]
        )

        assert _of_type(captured, "StepCompleteEvent")[0].data["elapsed_time"] >= 0.05

    def test_a_failing_step_reports_its_failure_count_without_warning(self, captured):
        """ActionFailedEvent owns the failure; a WARN here double-counts it."""
        orch = _orchestrator(["a", "b"])
        _run_level(orch, level_idx=2, level_actions=["a", "b"], pending=["a", "b"], failed=["b"])

        dones = _of_type(captured, "StepCompleteEvent")
        assert len(dones) == 1
        assert dones[0].data["failed"] == 1
        assert dones[0].level is EventLevel.INFO

    def test_the_tallies_account_for_every_action_in_the_level(self, captured):
        orch = _orchestrator(["a", "b"])
        _run_level(orch, level_idx=0, level_actions=["a", "b"], pending=["a", "b"], failed=["b"])

        data = _of_type(captured, "StepCompleteEvent")[0].data
        counted = data["completed"] + data["partial"] + data["skipped"] + data["failed"]
        assert counted + data["unfinished"] == 2

    def test_a_fully_complete_step_still_fires_complete(self, captured):
        orch = _orchestrator(["a"])
        _run_level(orch, level_idx=0, level_actions=["a"], pending=[])

        assert len(_of_type(captured, "StepCompleteEvent")) == 1


class TestConsoleIsNoLongerAProducer:
    """Step boundaries belong to the event stream; a direct print reaches only the terminal."""

    def test_the_orchestrator_holds_nothing_that_can_write_to_a_terminal(self, captured):
        orch = _orchestrator(["a", "b"])
        _run_level(orch, level_idx=0, level_actions=["a", "b"], pending=["a", "b"])

        writers = [
            name
            for name in vars(orch)
            if hasattr(getattr(orch, name), "print") or hasattr(getattr(orch, name), "write")
        ]
        assert writers == [], f"{writers} can bypass the event stream"

    def test_no_step_boundary_reaches_stdout_or_stderr(self, captured, capsys):
        orch = _orchestrator(["a", "b"])
        _run_level(orch, level_idx=0, level_actions=["a", "b"], pending=["a", "b"])

        captured_io = capsys.readouterr()
        assert captured_io.out == ""
        assert captured_io.err == ""


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

        wf._run_workflow_with_context(datetime.now())

        starts = _of_type(captured, "StepStartEvent")
        dones = _of_type(captured, "StepCompleteEvent")
        assert [e.data["step_index"] for e in starts] == [0, 1]
        assert [e.data["step_index"] for e in dones] == [0, 1]
        assert all(e.data["total_steps"] == 2 for e in starts)

    def test_the_sequential_console_carries_no_step_boundaries(self, captured):
        wf = self._workflow(["a"], [["a"]])
        wf._run_single_action = MagicMock(return_value=False)
        wf._run_storage_maintenance = MagicMock()

        wf._run_workflow_with_context(datetime.now())

        assert wf.runtime.console.file.getvalue() == ""


class TestWorkflowScale:
    """The action/step tally the up-front plan used to print now rides the step events."""

    def test_every_step_event_carries_the_total(self, captured):
        orch = _orchestrator(["a", "b"])
        _run_level(orch, level_idx=2, level_actions=["a", "b"], pending=["a", "b"], total_steps=7)

        starts = _of_type(captured, "StepStartEvent")
        dones = _of_type(captured, "StepCompleteEvent")
        assert starts[0].data["total_steps"] == 7
        assert dones[0].data["total_steps"] == 7
        assert "Step 3/7" in starts[0].message

    def test_the_start_event_states_the_action_count(self):
        from agent_actions.logging.events import WorkflowStartEvent

        event = WorkflowStartEvent(workflow_name="wf", action_count=3)
        assert event.message == "Running workflow wf (3 actions)"


class TestTheMessagesSayStep:
    """The rendered wording is the whole point of the event; pin it."""

    def test_a_fan_out_step_says_how_many_run_in_parallel(self, captured):
        orch = _orchestrator(["a", "b", "c"])
        _run_level(
            orch,
            level_idx=1,
            level_actions=["a", "b", "c"],
            pending=["a", "b", "c"],
            total_steps=5,
        )

        assert _of_type(captured, "StepStartEvent")[0].message == "Step 2/5: 3 actions (a, b, c)"

    def test_a_single_action_step_names_it(self, captured):
        orch = _orchestrator(["only"])
        _run_level(orch, level_idx=0, level_actions=["only"], pending=["only"], total_steps=2)

        assert _of_type(captured, "StepStartEvent")[0].message == "Step 1/2: only"

    def test_a_step_with_nothing_left_says_so(self, captured):
        orch = _orchestrator(["a"])
        _run_level(orch, level_idx=4, level_actions=["a"], pending=[], total_steps=9)

        assert (
            _of_type(captured, "StepStartEvent")[0].message
            == "Step 5/9: all actions already complete"
        )


class TestTheTalliesAreReal:
    def test_each_outcome_lands_in_its_own_bucket(self, captured):
        orch = _orchestrator(["w", "x", "y", "z"])
        _run_level(
            orch,
            level_idx=0,
            level_actions=["w", "x", "y", "z"],
            pending=[],
            completed=["w"],
            partial=["x"],
            skipped=["y"],
            failed=["z"],
        )

        data = _of_type(captured, "StepCompleteEvent")[0].data
        assert (data["completed"], data["partial"], data["skipped"], data["failed"]) == (1, 1, 1, 1)
        assert data["unfinished"] == 0

    def test_an_action_in_no_terminal_state_is_counted_unfinished(self, captured):
        orch = _orchestrator(["a", "b"])
        _run_level(orch, level_idx=0, level_actions=["a", "b"], pending=[], completed=["a"])

        data = _of_type(captured, "StepCompleteEvent")[0].data
        assert data["completed"] == 1
        assert data["unfinished"] == 1


class TestABatchPausedStepDoesNotClaimToBeComplete:
    def test_the_level_reports_itself_incomplete(self, captured):
        orch = _orchestrator(["a"])
        complete = _run_level(
            orch, level_idx=0, level_actions=["a"], pending=["a"], batch=["a"], total_steps=3
        )
        assert complete is False

    def test_the_event_says_paused_and_names_the_pending_jobs(self, captured):
        orch = _orchestrator(["a"])
        _run_level(
            orch, level_idx=0, level_actions=["a"], pending=["a"], batch=["a"], total_steps=3
        )

        done = _of_type(captured, "StepCompleteEvent")[0]
        assert done.data["batch_pending"] == ["a"]
        assert "paused" in done.message
        assert "complete" not in done.message


class TestAStepIsClosedWhateverHappens:
    """StepStartEvent without its StepCompleteEvent leaves every consumer unbalanced."""

    def test_an_action_that_raises_still_closes_its_step(self, captured):
        orch = _orchestrator(["a"])
        executor = MagicMock()

        async def boom(action, **kwargs):
            raise RuntimeError("tool exploded")

        executor.execute_action_async = boom
        state = _state_manager(pending=["a"])

        with pytest.raises(RuntimeError):
            asyncio.run(
                orch.execute_level_async(
                    LevelExecutionParams(
                        level_idx=0,
                        level_actions=["a"],
                        action_indices={"a": 0},
                        state_manager=state,
                        action_executor=executor,
                        total_steps=1,
                    )
                )
            )

        assert len(_of_type(captured, "StepStartEvent")) == 1
        assert len(_of_type(captured, "StepCompleteEvent")) == 1

    def test_an_interrupt_still_closes_its_step(self, captured):
        orch = _orchestrator(["a"])
        executor = MagicMock()

        async def interrupted(action, **kwargs):
            raise KeyboardInterrupt

        executor.execute_action_async = interrupted
        state = _state_manager(pending=["a"])

        with pytest.raises(KeyboardInterrupt):
            asyncio.run(
                orch.execute_level_async(
                    LevelExecutionParams(
                        level_idx=0,
                        level_actions=["a"],
                        action_indices={"a": 0},
                        state_manager=state,
                        action_executor=executor,
                        total_steps=1,
                    )
                )
            )

        assert len(_of_type(captured, "StepCompleteEvent")) == 1


class TestTheAsyncCoordinatorFiresTheSameEvents:
    """The parallel path is what a fan-out DAG actually takes."""

    @staticmethod
    def _workflow(execution_order, levels):
        wf = TestSequentialPathFiresTheSameEvents._workflow(execution_order, levels)

        async def execute_level(params):
            fire_step_start(
                params.level_idx, params.total_steps, params.level_actions, params.level_actions
            )
            fire_step_complete(
                params.level_idx,
                params.total_steps,
                0.0,
                params.level_actions,
                params.state_manager,
            )
            return True

        wf.services.core.action_level_orchestrator.execute_level_async = execute_level
        return wf

    def test_every_level_is_announced(self, captured):
        wf = self._workflow(["a", "b"], [["a"], ["b"]])
        wf._run_storage_maintenance = MagicMock()

        asyncio.run(wf.async_run())

        assert [e.data["step_index"] for e in _of_type(captured, "StepStartEvent")] == [0, 1]
        assert [e.data["total_steps"] for e in _of_type(captured, "StepStartEvent")] == [2, 2]

    def test_the_async_console_carries_no_step_boundaries(self, captured, capsys):
        wf = self._workflow(["a"], [["a"]])
        wf._run_storage_maintenance = MagicMock()

        asyncio.run(wf.async_run())

        assert wf.runtime.console.file.getvalue() == "", (
            "a console.print here reaches the terminal and never events.json"
        )
        io = capsys.readouterr()
        assert io.out == ""
        assert io.err == ""

    def test_the_workflow_start_event_fires_exactly_once(self, captured):
        wf = self._workflow(["a"], [["a"]])
        wf.event_logger = WorkflowEventLogger("wf", ["a"], wf.config, wf.services)
        wf._run_storage_maintenance = MagicMock()

        asyncio.run(wf.async_run())

        assert len(_of_type(captured, "WorkflowStartEvent")) == 1
