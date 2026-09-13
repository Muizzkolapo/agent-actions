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
    WorkflowFailedEvent,
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


def _complete(name, *, index=0, total=1, records=3, seconds=1.0, vendor="", model="", kind="llm"):
    event = ActionCompleteEvent(
        action_name=name,
        action_index=index,
        total_actions=total,
        execution_time=seconds,
        record_count=records,
        model_vendor=vendor,
        model_name=model,
        kind=kind,
    )
    return event


class TestOneLinePerAction:
    def test_a_starting_action_prints_nothing(self, rendered):
        out = rendered(
            StepStartEvent(
                step_index=0, total_steps=4, actions=["summarize"], pending=["summarize"]
            ),
            ActionStartEvent(action_name="summarize", action_index=0, total_actions=1),
        )
        assert "Step 1/4 summarize" in out
        assert "✓" not in out, "an action reports once, on completion"

    def test_a_sequential_step_names_its_action_on_both_lines(self, rendered):
        out = rendered(
            StepStartEvent(
                step_index=0, total_steps=4, actions=["summarize"], pending=["summarize"]
            ),
            _complete("summarize", records=3, seconds=29.6),
        )
        assert "Step 1/4 summarize" in out
        assert "✓ summarize  3 records in 29.6s" in out

    def test_a_parallel_step_names_each_action_on_its_own_line(self, rendered):
        out = rendered(
            StepStartEvent(
                step_index=1, total_steps=4, actions=["qa_1", "qa_2"], pending=["qa_1", "qa_2"]
            ),
            _complete("qa_1", records=3, seconds=80.1),
            _complete("qa_2", records=2, seconds=62.0),
        )
        assert "Step 2/4 2 actions: qa_1, qa_2" in out
        assert "qa_1  3 records in 1m20s" in out
        assert "qa_2  2 records in 1m02s" in out


class TestActionDetail:
    def test_a_single_record_is_not_pluralised(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            _complete("a", records=1),
        )
        assert "✓ a  1 record in" in out
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

    def test_a_tool_action_shows_no_model(self, rendered):
        """A tool carries its kind as the vendor and its impl as the model, so
        rendering them would echo the action's own name back at the reader."""
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["flat"], pending=["flat"]),
            _complete("flat", kind="tool", vendor="tool", model="flat"),
        )
        assert "✓ flat  3 records in 1.0s" in out
        assert "(" not in out

    def test_a_hitl_action_shows_no_model(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["ok"], pending=["ok"]),
            _complete("ok", kind="hitl", vendor="hitl", model="approve"),
        )
        assert "(" not in out

    def test_an_llm_action_with_no_model_configured_omits_it(self, rendered):
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
    def test_a_step_with_nothing_pending_names_what_is_already_done(self, rendered):
        out = rendered(
            StepStartEvent(step_index=3, total_steps=4, actions=["a", "b"], pending=[]),
            StepCompleteEvent(step_index=3, total_steps=4, elapsed_time=0.0, completed=2),
        )
        assert "Step 4/4 a, b" in out
        assert "already complete" in out
        assert "✓" not in out

    def test_a_finished_step_adds_no_line_of_its_own(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            _complete("a", seconds=5.0),
            StepCompleteEvent(step_index=0, total_steps=1, elapsed_time=5.0, completed=1),
        )
        assert out.count("Step 1/1") == 1
        assert "complete in 5.00s" not in out

    def test_a_step_waiting_on_batch_tells_the_user_to_run_again(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]),
            StepCompleteEvent(step_index=0, total_steps=1, elapsed_time=1.0, batch_pending=["a"]),
        )
        assert "1 batch job submitted — run again to continue" in out

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
        out = rendered(
            WorkflowStartEvent(workflow_name="quiz_gen", action_count=52),
            StepStartEvent(step_index=0, total_steps=36, actions=["a"], pending=["a"]),
        )
        assert "quiz_gen — 52 actions" in out
        assert "Step 1/36" in out, "the step count reaches the user on the first step line"
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


class TestAPlainStream:
    """Without Rich the markup escape has nothing to render it, so it must not run."""

    @staticmethod
    def _plain():
        renderer = ProgressRenderer(min_level=EventLevel.INFO, categories={"workflow", "action"})
        renderer._use_rich = False
        renderer._console = None
        return renderer

    @staticmethod
    def _capture(renderer, *events):
        import sys

        buf = io.StringIO()
        stderr, sys.stderr = sys.stderr, buf
        try:
            for event in events:
                renderer.handle(event)
        finally:
            sys.stderr = stderr
        return buf.getvalue()

    def test_an_error_is_shown_verbatim_without_escape_backslashes(self):
        out = self._capture(
            self._plain(),
            ActionFailedEvent(
                action_name="v",
                action_index=0,
                total_actions=1,
                error_message="field [red]answer[/red] missing",
            ),
        )
        assert "field [red]answer[/red] missing" in out
        assert "\\" not in out

    def test_results_still_render_without_rich(self):
        out = self._capture(
            self._plain(),
            StepStartEvent(step_index=0, total_steps=2, actions=["a"], pending=["a"]),
            _complete("a", records=2, seconds=1.0),
        )
        assert "Step 1/2 a" in out
        assert "OK a  2 records in 1.0s" in out


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


class TestStepNumbering:
    def test_the_last_step_is_the_total(self, rendered):
        out = rendered(
            StepStartEvent(step_index=11, total_steps=12, actions=["z"], pending=["z"]),
        )
        assert "Step 12/12 z" in out, "a run that ends at 11/12 looks like it stopped short"

    def test_the_first_step_is_one(self, rendered):
        out = rendered(StepStartEvent(step_index=0, total_steps=12, actions=["a"], pending=["a"]))
        assert "Step 1/12 a" in out


class TestAFanOutNamesItsActions:
    def test_a_multi_action_step_lists_them(self, rendered):
        out = rendered(
            StepStartEvent(
                step_index=0, total_steps=3, actions=["a", "b", "c"], pending=["a", "b", "c"]
            )
        )
        assert "Step 1/3 3 actions: a, b, c" in out

    def test_the_step_makes_no_claim_about_parallelism(self, rendered):
        """A level runs serially under --execution-mode sequential."""
        out = rendered(
            StepStartEvent(step_index=0, total_steps=3, actions=["a", "b"], pending=["a", "b"])
        )
        assert "parallel" not in out

    def test_a_wide_fan_out_is_truncated(self, rendered):
        names = [f"a{i}" for i in range(9)]
        out = rendered(StepStartEvent(step_index=0, total_steps=1, actions=names, pending=names))
        assert "9 actions: a0, a1, a2, a3 +5 more" in out


class TestVerboseShowsWhatIsInFlight:
    @staticmethod
    def _verbose():
        buf = io.StringIO()
        r = ProgressRenderer(
            min_level=EventLevel.DEBUG,
            categories=None,
            show_diagnostics=True,
            console=Console(file=buf, highlight=False, no_color=True, width=200),
        )
        return r, buf

    def test_an_action_announces_itself_when_the_run_is_verbose(self):
        r, buf = self._verbose()
        for e in (
            StepStartEvent(step_index=0, total_steps=2, actions=["a", "b"], pending=["a", "b"]),
            ActionStartEvent(action_name="a", action_index=0, total_actions=2),
        ):
            r.handle(e)
        assert "→ a" in buf.getvalue(), "a fan-out gives no other way to see what is running"

    def test_a_normal_run_still_reports_each_action_once(self, rendered):
        out = rendered(
            StepStartEvent(step_index=0, total_steps=2, actions=["a", "b"], pending=["a", "b"]),
            ActionStartEvent(action_name="a", action_index=0, total_actions=2),
        )
        assert "→" not in out


class TestAStepThatFinishedNothing:
    def test_the_message_does_not_claim_completion(self):
        event = StepCompleteEvent(
            step_index=0, total_steps=3, elapsed_time=1.0, completed=0, unfinished=2
        )
        assert "complete" not in event.message
        assert "2 unfinished" in event.message

    def test_a_step_that_finished_everything_says_complete(self):
        event = StepCompleteEvent(step_index=0, total_steps=3, elapsed_time=1.0, completed=2)
        assert event.message == "Step 1/3 complete in 1.00s"


class TestWorkflowHeaderGrammar:
    def test_a_single_action_workflow_is_not_pluralised(self, rendered):
        out = rendered(WorkflowStartEvent(workflow_name="w", action_count=1))
        assert "w — 1 action" in out
        assert "1 actions" not in out


class TestABatchActionIsMarkedAsOne:
    def test_batch_latency_is_labelled(self, rendered):
        """Sixteen minutes of provider queue reads like sixteen minutes of work."""
        event = _complete("x", records=40, seconds=974.0)
        event.data["mode"] = "batch"
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["x"], pending=["x"]), event
        )
        assert "16m14s (batch)" in out

    def test_an_online_action_is_not_labelled(self, rendered):
        event = _complete("x", seconds=2.0)
        event.data["mode"] = "online"
        out = rendered(
            StepStartEvent(step_index=0, total_steps=1, actions=["x"], pending=["x"]), event
        )
        assert "(batch)" not in out


class TestAFailedRunIsUnmistakable:
    def test_a_workflow_failure_is_reported(self, rendered):
        out = rendered(
            WorkflowFailedEvent(workflow_name="quiz_gen", error_message="schema 'answer' not found")
        )
        assert "schema 'answer' not found" in out
        assert "quiz_gen" in out, "the failure must name the workflow it belongs to"

    def test_the_footer_marks_a_failed_run(self, rendered):
        out = rendered(
            WorkflowCompleteEvent(
                workflow_name="w", elapsed_time=5.0, actions_completed=1, actions_failed=2
            )
        )
        assert "✗" in out
        assert "✓" not in out, "a run with failures must not be marked done"

    def test_the_footer_marks_a_clean_run(self, rendered):
        out = rendered(
            WorkflowCompleteEvent(workflow_name="w", elapsed_time=5.0, actions_completed=3)
        )
        assert "✓" in out
        assert "✗" not in out

    def test_the_footer_reports_partial_and_skipped(self, rendered):
        out = rendered(
            WorkflowCompleteEvent(
                workflow_name="w",
                elapsed_time=5.0,
                actions_completed=1,
                actions_partial=2,
                actions_skipped=3,
            )
        )
        assert "1 completed, 2 partial, 3 skipped" in out


class TestTheStreamSaysNothingItDoesNotNeedTo:
    def test_a_finished_step_emits_no_line(self, rendered):
        before = rendered(StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]))
        after = rendered(
            StepCompleteEvent(step_index=0, total_steps=1, elapsed_time=5.0, completed=1)
        )
        assert after == before, "the actions already reported; the step adds nothing"

    def test_a_starting_action_emits_no_line(self, rendered):
        before = rendered(StepStartEvent(step_index=0, total_steps=1, actions=["a"], pending=["a"]))
        after = rendered(ActionStartEvent(action_name="a", action_index=0, total_actions=1))
        assert after == before

    def test_several_pending_batch_jobs_are_pluralised(self, rendered):
        out = rendered(
            StepCompleteEvent(
                step_index=0, total_steps=1, elapsed_time=1.0, batch_pending=["a", "b"]
            )
        )
        assert "2 batch jobs submitted" in out
