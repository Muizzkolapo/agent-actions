"""Tests for RunResultsCollector handler."""

import json
from datetime import UTC, datetime

import pytest

from agent_actions.logging.core.events import BaseEvent
from agent_actions.logging.events.handlers.run_results import (
    RunResultsCollector,
)
from agent_actions.logging.events.workflow_events import (
    ActionCompleteEvent,
    ActionFailedEvent,
    ActionSkipEvent,
    ActionStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    WorkflowStartEvent,
)


@pytest.fixture
def temp_output_dir(tmp_path):
    """Provide a temporary output directory."""
    return tmp_path / "output"


@pytest.fixture
def collector(temp_output_dir):
    """Provide a RunResultsCollector instance."""
    return RunResultsCollector(output_dir=temp_output_dir, workflow_name="test_workflow")


class TestRunResultsCollectorAccepts:
    """Tests for RunResultsCollector.accepts()."""

    def test_accepts_workflow_events(self, collector):
        """Test that workflow events are accepted."""
        event = WorkflowStartEvent(workflow_name="test", action_count=1)
        assert collector.accepts(event)

    def test_accepts_agent_events(self, collector):
        """Test that agent events are accepted."""
        event = ActionCompleteEvent(action_name="test", action_index=0)
        assert collector.accepts(event)

    def test_rejects_other_events(self, collector):
        """Test that non-workflow/agent events are rejected."""
        event = BaseEvent(category="batch", message="test")
        assert not collector.accepts(event)

        event = BaseEvent(category="llm", message="test")
        assert not collector.accepts(event)


class TestWorkflowEventHandling:
    """Tests for workflow event handling."""

    def test_handle_workflow_start(self, collector):
        """Test WorkflowStartEvent handling."""
        event = WorkflowStartEvent(
            workflow_name="my_workflow",
            action_count=5,
            execution_mode="parallel",
        )
        event.meta.timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        collector.handle(event)

        assert collector._metadata["workflow_name"] == "my_workflow"
        assert collector._metadata["action_count"] == 5
        assert collector._metadata["execution_mode"] == "parallel"
        assert collector._metadata["started_at"] == "2024-01-15T10:00:00+00:00"
        assert collector._metadata["status"] == "running"

    def test_handle_workflow_complete(self, collector, temp_output_dir):
        """Test WorkflowCompleteEvent handling."""
        # First start the workflow
        start_event = WorkflowStartEvent(workflow_name="test", action_count=1)
        collector.handle(start_event)

        # Then complete it
        event = WorkflowCompleteEvent(
            workflow_name="test",
            elapsed_time=120.5,
            actions_completed=1,
        )
        event.meta.timestamp = datetime(2024, 1, 15, 10, 2, 0, tzinfo=UTC)

        collector.handle(event)

        assert collector._metadata["completed_at"] == "2024-01-15T10:02:00+00:00"
        assert collector._metadata["elapsed_time"] == 120.5
        assert collector._metadata["status"] == "success"

        # Should have written run_results.json
        assert (temp_output_dir / "target" / "run_results.json").exists()

    def test_handle_workflow_failed(self, collector, temp_output_dir):
        """Test WorkflowFailedEvent handling."""
        start_event = WorkflowStartEvent(workflow_name="test", action_count=1)
        collector.handle(start_event)

        event = WorkflowFailedEvent(
            workflow_name="test",
            error_message="Something went wrong",
            error_type="RuntimeError",
            elapsed_time=30.0,
            failed_action="broken_agent",
        )

        collector.handle(event)

        assert collector._metadata["status"] == "error"
        assert collector._metadata["error"]["message"] == "Something went wrong"
        assert collector._metadata["error"]["type"] == "RuntimeError"
        assert collector._metadata["error"]["failed_action"] == "broken_agent"

    def test_invocation_id_captured(self, collector):
        """Test that invocation_id is captured from events."""
        event = WorkflowStartEvent(workflow_name="test", action_count=1)
        event.meta.invocation_id = "inv-12345"

        collector.handle(event)

        assert collector._metadata["invocation_id"] == "inv-12345"


class TestAgentEventHandling:
    """Tests for agent event handling."""

    def test_handle_agent_complete(self, collector):
        """Test ActionCompleteEvent handling."""
        event = ActionCompleteEvent(
            action_name="transform",
            action_index=1,
            total_actions=3,
            execution_time=25.5,
            output_path="/output/transform",
            record_count=100,
            tokens={"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
        )

        collector.handle(event)

        result = collector._results["transform"]
        assert result.status == "success"
        assert result.execution_time == 25.5
        assert result.output_folder == "/output/transform"
        assert result.record_count == 100
        assert result.tokens["total_tokens"] == 700

    def test_handle_agent_complete_creates_entry(self, collector):
        """Test ActionCompleteEvent creates new result entry."""
        event = ActionCompleteEvent(
            action_name="extract_data",
            action_index=0,
            total_actions=3,
        )
        event.meta.timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        collector.handle(event)

        assert "extract_data" in collector._results
        result = collector._results["extract_data"]
        assert result.action_name == "extract_data"
        assert result.action_index == 0
        assert result.status == "success"

    def test_handle_agent_failed_existing(self, collector):
        """Test ActionFailedEvent for an agent that was completed."""
        # Complete the agent first
        collector.handle(ActionCompleteEvent(action_name="failing", action_index=0))

        # Fail it
        event = ActionFailedEvent(
            action_name="failing",
            action_index=0,
            total_actions=3,
            error_message="Connection refused",
            error_type="ConnectionError",
            execution_time=5.0,
        )

        collector.handle(event)

        result = collector._results["failing"]
        assert result.status == "error"
        assert result.error_message == "Connection refused"
        assert result.execution_time == 5.0

    def test_handle_agent_failed_new(self, collector):
        """Test ActionFailedEvent for an agent that wasn't started."""
        event = ActionFailedEvent(
            action_name="instant_fail",
            action_index=0,
            total_actions=3,
            error_message="Validation error",
            error_type="ValidationError",
        )

        collector.handle(event)

        assert "instant_fail" in collector._results
        result = collector._results["instant_fail"]
        assert result.status == "error"


class TestTokenAccumulation:
    """Tests for token accumulation."""

    def test_tokens_accumulated_across_agents(self, collector):
        """Test that tokens are accumulated from all agents."""
        # Start workflow
        collector.handle(WorkflowStartEvent(workflow_name="test", action_count=3))

        # Complete multiple agents with tokens
        for i, (name, tokens) in enumerate(
            [
                ("agent1", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}),
                ("agent2", {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}),
                ("agent3", {"prompt_tokens": 300, "completion_tokens": 150, "total_tokens": 450}),
            ]
        ):
            collector.handle(ActionCompleteEvent(action_name=name, action_index=i, tokens=tokens))

        assert collector._total_tokens["prompt_tokens"] == 600
        assert collector._total_tokens["completion_tokens"] == 300
        assert collector._total_tokens["total_tokens"] == 900


class TestFlushAndOutput:
    """Tests for flush and output generation."""

    def test_flush_creates_target_directory(self, collector, temp_output_dir):
        """Test that flush creates target directory."""
        collector.handle(WorkflowStartEvent(workflow_name="test", action_count=0))
        collector.handle(WorkflowCompleteEvent(workflow_name="test"))

        assert (temp_output_dir / "target").exists()

    def test_flush_writes_run_results_json(self, collector, temp_output_dir):
        """Test that flush writes run_results.json."""
        collector.handle(WorkflowStartEvent(workflow_name="test", action_count=1))
        collector.handle(
            ActionCompleteEvent(
                action_name="agent1",
                action_index=0,
                tokens={"prompt_tokens": 100, "total_tokens": 100},
            )
        )
        collector.handle(WorkflowCompleteEvent(workflow_name="test", elapsed_time=10.0))

        output_path = temp_output_dir / "target" / "run_results.json"
        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)

        assert "metadata" in data
        assert "results" in data
        assert "elapsed_time" in data
        assert "tokens" in data

    def test_output_structure(self, collector, temp_output_dir):
        """Test the structure of run_results.json."""
        collector.handle(WorkflowStartEvent(workflow_name="my_workflow", action_count=2))
        collector.handle(
            ActionCompleteEvent(
                action_name="agent1",
                action_index=0,
                execution_time=5.0,
                tokens={"total_tokens": 100},
            )
        )
        collector.handle(
            ActionFailedEvent(action_name="agent2", action_index=1, error_message="failed")
        )
        collector.handle(
            WorkflowCompleteEvent(
                workflow_name="my_workflow",
                elapsed_time=5.0,
                actions_completed=1,
            )
        )

        output_path = temp_output_dir / "target" / "run_results.json"
        with open(output_path) as f:
            data = json.load(f)

        # Check metadata
        assert data["metadata"]["workflow_name"] == "my_workflow"
        assert data["metadata"]["action_count"] == 2
        assert data["metadata"]["status"] == "success"

        # Check results are sorted by agent_index
        assert len(data["results"]) == 2
        assert data["results"][0]["action_name"] == "agent1"
        assert data["results"][1]["action_name"] == "agent2"

    def test_flush_without_output_dir(self):
        """Test that flush does nothing without output_dir."""
        collector = RunResultsCollector()  # No output_dir
        collector.handle(WorkflowStartEvent(workflow_name="test", action_count=0))

        # Should not raise
        collector.flush()

    def test_results_sorted_by_index(self, collector, temp_output_dir):
        """Test that results are sorted by agent_index in output."""
        collector.handle(WorkflowStartEvent(workflow_name="test", action_count=3))

        # Add agents out of order
        for name, idx in [("third", 2), ("first", 0), ("second", 1)]:
            collector.handle(ActionCompleteEvent(action_name=name, action_index=idx))

        collector.handle(WorkflowCompleteEvent(workflow_name="test"))

        output_path = temp_output_dir / "target" / "run_results.json"
        with open(output_path) as f:
            data = json.load(f)

        indices = [r["action_index"] for r in data["results"]]
        assert indices == [0, 1, 2]


class TestGetSummary:
    """Tests for get_summary method."""

    def test_get_summary_all_statuses(self, collector):
        """Test summary covers all status types: success, skipped, error, running."""
        collector.handle(WorkflowStartEvent(workflow_name="test", action_count=4))

        collector.handle(ActionCompleteEvent(action_name="ok", action_index=0))
        collector.handle(ActionSkipEvent(action_name="skip1", action_index=1, skip_reason="done"))
        collector.handle(
            ActionFailedEvent(action_name="fail1", action_index=2, error_message="boom")
        )
        # Simulate a running agent (created by RecordEmptyOutputEvent before completion)
        from agent_actions.logging.events.data_pipeline_events import RecordEmptyOutputEvent

        collector.handle(RecordEmptyOutputEvent(action_name="still_running", record_index=0))

        summary = collector.get_summary()

        assert summary["success"] == 1
        assert summary["skipped"] == 1
        assert summary["error"] == 1
        assert summary["running"] == 1


class TestUniqueIdGeneration:
    """Tests for unique_id generation in results."""

    def test_unique_id_format(self, collector):
        """Test that unique_id follows workflow.agent_name format."""
        collector.handle(WorkflowStartEvent(workflow_name="my_workflow", action_count=1))
        collector.handle(ActionCompleteEvent(action_name="my_agent", action_index=0))

        result = collector._results["my_agent"]
        assert result.unique_id == "my_workflow.my_agent"

    def test_unique_id_updates_with_workflow(self, collector):
        """Test that unique_id uses workflow name from start event."""
        # Handle workflow start which sets the workflow_name
        collector.handle(WorkflowStartEvent(workflow_name="actual_workflow", action_count=1))
        collector.handle(ActionCompleteEvent(action_name="agent", action_index=0))

        result = collector._results["agent"]
        assert result.unique_id == "actual_workflow.agent"


class TestAgentSkipHandling:
    """Tests for ActionSkipEvent handling."""

    def test_handle_agent_skip(self, collector):
        """Test ActionSkipEvent creates a skipped result with timestamp."""
        collector.handle(WorkflowStartEvent(workflow_name="test", action_count=2))
        event = ActionSkipEvent(
            action_name="cached_agent",
            action_index=0,
            total_actions=2,
            skip_reason="already completed",
        )
        event.meta.timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        collector.handle(event)

        assert "cached_agent" in collector._results
        result = collector._results["cached_agent"]
        assert result.status == "skipped"
        assert result.skip_reason == "already completed"
        assert result.completed_at == datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

    def test_skip_counted_in_summary(self, collector):
        """Test that skipped agents appear in summary."""
        collector.handle(WorkflowStartEvent(workflow_name="test", action_count=2))
        collector.handle(ActionSkipEvent(action_name="skip1", action_index=0, skip_reason="done"))
        collector.handle(ActionCompleteEvent(action_name="run1", action_index=1))

        summary = collector.get_summary()
        assert summary["skipped"] == 1
        assert summary["success"] == 1


class TestActionStartEventHandling:
    """Tests for ActionStartEvent handling (1-B)."""

    def test_handle_agent_start_creates_entry(self, collector):
        """ActionStartEvent creates a running entry with started_at."""
        event = ActionStartEvent(
            action_name="my_agent",
            action_index=2,
            total_actions=5,
        )
        event.meta.timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        collector.handle(event)

        assert "my_agent" in collector._results
        result = collector._results["my_agent"]
        assert result.status == "running"
        assert result.action_index == 2
        assert result.started_at == datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

    def test_start_then_complete_preserves_started_at(self, collector):
        """started_at from ActionStartEvent survives ActionCompleteEvent."""
        start = ActionStartEvent(action_name="a", action_index=1, total_actions=3)
        start.meta.timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        collector.handle(start)

        complete = ActionCompleteEvent(action_name="a", action_index=1, execution_time=5.0)
        complete.meta.timestamp = datetime(2024, 1, 15, 10, 0, 5, tzinfo=UTC)
        collector.handle(complete)

        result = collector._results["a"]
        assert result.status == "success"
        assert result.started_at == datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        assert result.completed_at == datetime(2024, 1, 15, 10, 0, 5, tzinfo=UTC)


class TestAgentIndexUpdatedOnExistingEntry:
    """Tests for agent_index update on pre-existing entries (1-A)."""

    def test_empty_output_then_complete_updates_index(self, collector):
        """RecordEmptyOutputEvent creates entry with index=0; ActionCompleteEvent fixes it."""
        from agent_actions.logging.events.data_pipeline_events import RecordEmptyOutputEvent

        collector.handle(RecordEmptyOutputEvent(action_name="agent_x", record_index=0))
        assert collector._results["agent_x"].action_index == 0

        collector.handle(ActionCompleteEvent(action_name="agent_x", action_index=3))
        assert collector._results["agent_x"].action_index == 3

    def test_empty_output_then_skip_updates_index(self, collector):
        """RecordEmptyOutputEvent creates entry with index=0; ActionSkipEvent fixes it."""
        from agent_actions.logging.events.data_pipeline_events import RecordEmptyOutputEvent

        collector.handle(RecordEmptyOutputEvent(action_name="agent_y", record_index=0))
        collector.handle(
            ActionSkipEvent(action_name="agent_y", action_index=2, skip_reason="cached")
        )
        assert collector._results["agent_y"].action_index == 2

    def test_empty_output_then_failed_updates_index(self, collector):
        """RecordEmptyOutputEvent creates entry with index=0; ActionFailedEvent fixes it."""
        from agent_actions.logging.events.data_pipeline_events import RecordEmptyOutputEvent

        collector.handle(RecordEmptyOutputEvent(action_name="agent_z", record_index=0))
        collector.handle(
            ActionFailedEvent(action_name="agent_z", action_index=4, error_message="boom")
        )
        assert collector._results["agent_z"].action_index == 4
