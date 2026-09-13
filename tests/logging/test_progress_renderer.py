"""The console renders a run as a grouped progress stream, one line per action.

Two lines per action plus a banner per step boundary buries the run in its own
bookkeeping. The renderer groups results under the step that produced them and
says what the person running the workflow needs: how many records, how long,
which model, and what to do when something fails.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.core.handlers.progress import ProgressRenderer
from agent_actions.logging.events import (
    ActionCompleteEvent,
    ActionFailedEvent,
    ActionSkipEvent,
    ActionStartEvent,
    StepCompleteEvent,
    StepStartEvent,
    WorkflowCompleteEvent,
    WorkflowStartEvent,
)


@pytest.fixture
def rendered():
    buf = io.StringIO()
    renderer = ProgressRenderer(
        min_level=EventLevel.INFO,
        categories={"workflow", "action", "batch"},
        console=Console(file=buf, highlight=False, no_color=True, width=200),
    )

    def run(*events: BaseEvent) -> str:
        for event in events:
            if renderer.accepts(event):
                renderer.handle(event)
        return buf.getvalue()

    return run


def _complete(name, *, index=0, total=1, records=3, seconds=1.0, vendor="", model=""):
    event = ActionCompleteEvent(
        action_name=name,
        action_index=index,
        total_actions=total,
        execution_time=seconds,
        record_count=records,
    )
    event.data["model_vendor"] = vendor
    event.data["model_name"] = model
    return event


class TestOneLinePerAction:
    def test_a_starting_action_prints_nothing(self, rendered):
        out = rendered(
            StepStartEvent(
                step_index=0, total_steps=4, actions=["summarize"], pending=["summarize"]
            ),
            ActionStartEvent(action_name="summarize", action_index=0, total_actions=1),
        )
        assert "summarize" in out
        assert out.count("summarize") == 1, "the step header already named it"

    def test_a_sequential_step_names_its_action_in_the_header_only(self, rendered):
        out = rendered(
            StepStartEvent(
                step_index=0, total_steps=4, actions=["summarize"], pending=["summarize"]
            ),
            _complete("summarize", records=3, seconds=29.6),
        )
        assert "Step 0/4 summarize" in out
        assert "3 records in 29.6s" in out
        assert out.count("summarize") == 1

    def test_a_parallel_step_names_each_action_on_its_own_line(self, rendered):
        out = rendered(
            StepStartEvent(
                step_index=1, total_steps=4, actions=["qa_1", "qa_2"], pending=["qa_1", "qa_2"]
            ),
            _complete("qa_1", records=3, seconds=80.1),
            _complete("qa_2", records=2, seconds=62.0),
        )
        assert "Step 1/4 2 in parallel" in out
        assert "qa_1  3 records in 80.1s" in out
        assert "qa_2  2 records in 62.0s" in out


class TestActionDetail:
    def test_a_single_record_is_not_pluralised(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            _complete("a", records=1),
        )
        assert "1 record in" in out
        assert "1 records" not in out

    def test_the_model_that_produced_the_records_is_named(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            _complete("a", vendor="ollama", model="gpt-oss:120b"),
        )
        assert "(ollama/gpt-oss:120b)" in out

    def test_a_long_action_reports_minutes(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            _complete("a", seconds=125.0),
        )
        assert "in 2m05s" in out

    def test_a_toolless_action_omits_the_model(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            _complete("a"),
        )
        assert "(" not in out


class TestFailureIsActionable:
    def test_a_failed_action_shows_the_error_not_an_index(self, rendered):
        out = rendered(
            StepStartEvent(step_index=2, total_steps=4, actions=["verify"], pending=["verify"]),
            ActionFailedEvent(
                action_name="verify",
                action_index=2,
                total_actions=4,
                error_message="answer verification failed for 2 records",
            ),
        )
        assert "answer verification failed for 2 records" in out
        assert "3/4 ERROR" not in out

    def test_a_suggestion_is_shown_under_the_failure(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["v"], pending=["v"]),
            ActionFailedEvent(
                action_name="v",
                action_index=0,
                total_actions=1,
                error_message="no such model",
                suggestion="set model_name in agent_config",
            ),
        )
        assert "set model_name in agent_config" in out

    def test_markup_in_an_error_is_shown_not_interpreted(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["v"], pending=["v"]),
            ActionFailedEvent(
                action_name="v",
                action_index=0,
                total_actions=1,
                error_message="field [red]answer[/red] missing",
            ),
        )
        assert "[red]answer[/red] missing" in out


class TestStepShape:
    def test_a_step_with_nothing_pending_says_so_and_lists_no_actions(self, rendered):
        out = rendered(
            StepStartEvent(step_index=3, total_steps=4, actions=["a", "b"], pending=[]),
            StepCompleteEvent(step_index=3, total_steps=4, elapsed_time=0.0, completed=2),
        )
        assert "Step 3/4 a, b" in out
        assert "already complete" in out
        assert "✓" not in out

    def test_a_finished_step_adds_no_line_of_its_own(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            _complete("a", seconds=5.0),
            StepCompleteEvent(step_index=0, total_steps=1, elapsed_time=5.0, completed=1),
        )
        assert out.count("Step 0/1") == 1
        assert "complete in 5.00s" not in out

    def test_a_step_waiting_on_batch_tells_the_user_to_run_again(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            StepCompleteEvent(step_index=0, total_steps=1, elapsed_time=1.0, batch_pending=["a"]),
        )
        assert "run again to continue" in out

    def test_a_skipped_action_gives_its_reason(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            ActionSkipEvent(
                action_name="a", action_index=0, total_actions=1, skip_reason="guard excluded it"
            ),
        )
        assert "guard excluded it" in out
        assert "1/1 SKIP" not in out, "the step, not a running index, locates the action"


class TestWorkflowFraming:
    def test_the_header_states_the_scale_of_the_run(self, rendered):
        out = rendered(WorkflowStartEvent(workflow_name="quiz_gen", action_count=52, step_count=36))
        assert "quiz_gen" in out
        assert "52 actions, 36 steps" in out
        assert "Running workflow" not in out, "the header is the workflow, not a log line about it"

    def test_the_footer_totals_the_run(self, rendered):
        out = rendered(
            WorkflowCompleteEvent(
                workflow_name="quiz_gen",
                elapsed_time=702.8,
                actions_completed=50,
                actions_failed=2,
            )
        )
        assert "11m42s" in out
        assert "50 completed" in out
        assert "2 failed" in out

    def test_a_clean_run_does_not_mention_failures(self, rendered):
        out = rendered(
            WorkflowCompleteEvent(workflow_name="quiz_gen", elapsed_time=10.0, actions_completed=3)
        )
        assert "3 completed" in out
        assert "failed" not in out


class TestNothingIsSwallowed:
    def test_a_warning_from_elsewhere_still_reaches_the_console(self, rendered):
        out = rendered(
            BaseEvent(level=EventLevel.WARN, category="llm", message="rate limited, retrying")
        )
        assert "rate limited, retrying" in out

    def test_a_diagnostic_warning_is_still_kept_off_the_console(self, rendered):
        out = rendered(
            BaseEvent(level=EventLevel.WARN, category="prompt", message="internal", diagnostic=True)
        )
        assert out == ""


class TestTheModelReachesTheEvent:
    """The renderer can only name the model if the producers put it on the event."""

    @staticmethod
    def _captured():
        from agent_actions.logging.core.manager import EventManager

        class _Capture:
            def __init__(self):
                self.events = []

            def accepts(self, event):
                return True

            def handle(self, event):
                self.events.append(event)

            def flush(self):
                pass

        EventManager.reset()
        capture = _Capture()
        EventManager.get().register(capture)
        return capture

    @staticmethod
    def _result(duration=1.0, records=2):
        from unittest.mock import MagicMock

        from agent_actions.workflow.executor import ExecutionMetrics

        result = MagicMock()
        result.success = True
        result.status = "completed"
        result.output_folder = "/out"
        result.metrics = ExecutionMetrics(duration=duration, record_count=records)
        return result

    def test_the_parallel_path_names_the_model(self):
        from agent_actions.logging.core.manager import EventManager
        from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

        capture = self._captured()
        try:
            orch = ActionLevelOrchestrator(
                ["a"], {"a": {"model_vendor": "ollama", "model_name": "gpt-oss:120b"}}
            )
            orch._fire_action_result_event("a", 0, 1, self._result(), "online")
            done = [e for e in capture.events if e.event_type == "ActionCompleteEvent"]
            assert len(done) == 1
            assert done[0].data["model_vendor"] == "ollama"
            assert done[0].data["model_name"] == "gpt-oss:120b"
        finally:
            EventManager.reset()

    def test_the_sequential_path_names_the_model(self):
        from datetime import datetime

        from agent_actions.logging.core.manager import EventManager
        from agent_actions.workflow.execution_events import WorkflowEventLogger
        from agent_actions.workflow.models import ActionLogParams

        capture = self._captured()
        try:
            from unittest.mock import MagicMock

            event_logger = WorkflowEventLogger("wf", ["a"], MagicMock(), MagicMock())
            event_logger.log_action_result(
                ActionLogParams(
                    idx=0,
                    action_name="a",
                    total_actions=1,
                    result=self._result(),
                    end_time=datetime.now(),
                    duration=1.0,
                    run_mode="online",
                    action_config={"model_vendor": "openai", "model_name": "gpt-5"},
                )
            )
            done = [e for e in capture.events if e.event_type == "ActionCompleteEvent"]
            assert len(done) == 1
            assert done[0].data["model_vendor"] == "openai"
            assert done[0].data["model_name"] == "gpt-5"
        finally:
            EventManager.reset()

    def test_a_tool_action_carries_no_model(self):
        from agent_actions.logging.core.manager import EventManager
        from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

        capture = self._captured()
        try:
            orch = ActionLevelOrchestrator(["t"], {"t": {"kind": "tool"}})
            orch._fire_action_result_event("t", 0, 1, self._result(), "online")
            done = [e for e in capture.events if e.event_type == "ActionCompleteEvent"]
            assert done[0].data["model_vendor"] == ""
            assert done[0].data["model_name"] == ""
        finally:
            EventManager.reset()


class TestTheFactoryInstallsTheRenderer:
    def test_the_console_handler_for_a_run_is_the_progress_renderer(self, tmp_path):
        from agent_actions.logging.core.handlers.console import ConsoleEventHandler
        from agent_actions.logging.factory import LoggerFactory

        LoggerFactory.reset()
        try:
            manager = LoggerFactory.initialize(output_dir=tmp_path, workflow_name="wf")
            consoles = [h for h in manager._handlers if isinstance(h, ConsoleEventHandler)]
            assert len(consoles) == 1
            assert isinstance(consoles[0], ProgressRenderer)
        finally:
            LoggerFactory.reset()
