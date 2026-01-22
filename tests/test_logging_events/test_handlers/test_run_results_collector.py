"""Tests for RunResultsCollector handler.

This module tests:
- Workflow event collection
- Agent event collection
- run_results.json generation
- Token accumulation
- Status tracking
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel, EventMeta
from agent_actions.logging.events.types import (
    WorkflowStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    AgentStartEvent,
    AgentCompleteEvent,
    AgentSkipEvent,
    AgentCachedEvent,
    AgentFailedEvent,
)
from agent_actions.logging.events.handlers.run_results import (
    RunResultsCollector,
    AgentResult,
)


@pytest.fixture
def temp_output_dir(tmp_path):
    """Provide a temporary output directory."""
    return tmp_path / "output"


@pytest.fixture
def collector(temp_output_dir):
    """Provide a RunResultsCollector instance."""
    return RunResultsCollector(output_dir=temp_output_dir, workflow_name="test_workflow")


class TestAgentResult:
    """Tests for AgentResult dataclass."""

    def test_agent_result_defaults(self):
        """Test AgentResult default values."""
        result = AgentResult(
            unique_id="test.agent",
            agent_name="agent",
            agent_index=0,
            status="success",
        )

        assert result.execution_time == 0.0
        assert result.output_folder == ""
        assert result.record_count == 0
        assert result.tokens == {}
        assert result.error_message == ""
        assert result.skip_reason == ""
        assert result.started_at is None
        assert result.completed_at is None

    def test_agent_result_to_dict(self):
        """Test AgentResult serialization."""
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = AgentResult(
            unique_id="workflow.agent",
            agent_name="agent",
            agent_index=0,
            status="success",
            execution_time=12.5,
            output_folder="/output/agent",
            record_count=100,
            tokens={"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
            started_at=ts,
            completed_at=ts,
        )

        d = result.to_dict()

        assert d["unique_id"] == "workflow.agent"
        assert d["agent_name"] == "agent"
        assert d["agent_index"] == 0
        assert d["status"] == "success"
        assert d["execution_time"] == 12.5
        assert d["record_count"] == 100
        assert d["tokens"]["total_tokens"] == 700
        assert d["timing"]["started_at"] == "2024-01-15T10:30:00+00:00"

    def test_agent_result_to_dict_excludes_empty(self):
        """Test that empty error/skip fields are null in output."""
        result = AgentResult(
            unique_id="test.agent",
            agent_name="agent",
            agent_index=0,
            status="success",
        )

        d = result.to_dict()

        assert d["error_message"] is None
        assert d["skip_reason"] is None


class TestRunResultsCollectorInit:
    """Tests for RunResultsCollector initialization."""

    def test_init_with_output_dir(self, temp_output_dir):
        """Test initialization with output directory."""
        collector = RunResultsCollector(output_dir=temp_output_dir)
        assert collector.output_dir == temp_output_dir

    def test_init_with_workflow_name(self, temp_output_dir):
        """Test initialization with workflow name."""
        collector = RunResultsCollector(
            output_dir=temp_output_dir, workflow_name="my_workflow"
        )
        assert collector.workflow_name == "my_workflow"
        assert collector._metadata["workflow_name"] == "my_workflow"

    def test_init_default_metadata(self, temp_output_dir):
        """Test default metadata values."""
        collector = RunResultsCollector(output_dir=temp_output_dir)

        assert collector._metadata["invocation_id"] is None
        assert collector._metadata["agent_count"] == 0
        assert collector._metadata["execution_mode"] == "sequential"
        assert collector._metadata["status"] == "running"

    def test_init_default_tokens(self, temp_output_dir):
        """Test default token counters."""
        collector = RunResultsCollector(output_dir=temp_output_dir)

        assert collector._total_tokens["prompt_tokens"] == 0
        assert collector._total_tokens["completion_tokens"] == 0
        assert collector._total_tokens["total_tokens"] == 0

    def test_set_output_dir(self, temp_output_dir):
        """Test set_output_dir method."""
        collector = RunResultsCollector()
        assert collector.output_dir is None

        collector.set_output_dir(temp_output_dir)
        assert collector.output_dir == temp_output_dir


class TestRunResultsCollectorAccepts:
    """Tests for RunResultsCollector.accepts()."""

    def test_accepts_workflow_events(self, collector):
        """Test that workflow events are accepted."""
        event = WorkflowStartEvent(workflow_name="test", agent_count=1)
        assert collector.accepts(event)

    def test_accepts_agent_events(self, collector):
        """Test that agent events are accepted."""
        event = AgentStartEvent(agent_name="test")
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
            agent_count=5,
            execution_mode="parallel",
        )
        event.meta.timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        collector.handle(event)

        assert collector._metadata["workflow_name"] == "my_workflow"
        assert collector._metadata["agent_count"] == 5
        assert collector._metadata["execution_mode"] == "parallel"
        assert collector._metadata["started_at"] == "2024-01-15T10:00:00+00:00"
        assert collector._metadata["status"] == "running"

    def test_handle_workflow_complete(self, collector, temp_output_dir):
        """Test WorkflowCompleteEvent handling."""
        # First start the workflow
        start_event = WorkflowStartEvent(workflow_name="test", agent_count=1)
        collector.handle(start_event)

        # Then complete it
        event = WorkflowCompleteEvent(
            workflow_name="test",
            elapsed_time=120.5,
            agents_completed=1,
        )
        event.meta.timestamp = datetime(2024, 1, 15, 10, 2, 0, tzinfo=timezone.utc)

        collector.handle(event)

        assert collector._metadata["completed_at"] == "2024-01-15T10:02:00+00:00"
        assert collector._metadata["elapsed_time"] == 120.5
        assert collector._metadata["status"] == "success"

        # Should have written run_results.json
        assert (temp_output_dir / "target" / "run_results.json").exists()

    def test_handle_workflow_failed(self, collector, temp_output_dir):
        """Test WorkflowFailedEvent handling."""
        start_event = WorkflowStartEvent(workflow_name="test", agent_count=1)
        collector.handle(start_event)

        event = WorkflowFailedEvent(
            workflow_name="test",
            error_message="Something went wrong",
            error_type="RuntimeError",
            elapsed_time=30.0,
            failed_agent="broken_agent",
        )

        collector.handle(event)

        assert collector._metadata["status"] == "error"
        assert collector._metadata["error"]["message"] == "Something went wrong"
        assert collector._metadata["error"]["type"] == "RuntimeError"
        assert collector._metadata["error"]["failed_agent"] == "broken_agent"

    def test_invocation_id_captured(self, collector):
        """Test that invocation_id is captured from events."""
        event = WorkflowStartEvent(workflow_name="test", agent_count=1)
        event.meta.invocation_id = "inv-12345"

        collector.handle(event)

        assert collector._metadata["invocation_id"] == "inv-12345"


class TestAgentEventHandling:
    """Tests for agent event handling."""

    def test_handle_agent_start(self, collector):
        """Test AgentStartEvent handling."""
        event = AgentStartEvent(
            agent_name="extract_data",
            agent_index=0,
            total_agents=3,
            agent_type="extractor",
        )
        event.meta.timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        collector.handle(event)

        assert "extract_data" in collector._results
        result = collector._results["extract_data"]
        assert result.agent_name == "extract_data"
        assert result.agent_index == 0
        assert result.status == "running"
        assert result.started_at is not None

    def test_handle_agent_complete(self, collector):
        """Test AgentCompleteEvent handling."""
        # First start the agent
        start_event = AgentStartEvent(agent_name="transform", agent_index=1)
        collector.handle(start_event)

        # Then complete it
        event = AgentCompleteEvent(
            agent_name="transform",
            agent_index=1,
            total_agents=3,
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

    def test_handle_agent_skip(self, collector):
        """Test AgentSkipEvent handling."""
        event = AgentSkipEvent(
            agent_name="already_done",
            agent_index=0,
            total_agents=3,
            skip_reason="output exists",
        )

        collector.handle(event)

        assert "already_done" in collector._results
        result = collector._results["already_done"]
        assert result.status == "skipped"
        assert result.skip_reason == "output exists"

    def test_handle_agent_cached(self, collector):
        """Test AgentCachedEvent handling."""
        event = AgentCachedEvent(
            agent_name="cached_agent",
            agent_index=0,
            total_agents=3,
            cache_key="abc123",
        )

        collector.handle(event)

        assert "cached_agent" in collector._results
        result = collector._results["cached_agent"]
        assert result.status == "cached"

    def test_handle_agent_failed_existing(self, collector):
        """Test AgentFailedEvent for an agent that was started."""
        # Start the agent
        start_event = AgentStartEvent(agent_name="failing", agent_index=0)
        collector.handle(start_event)

        # Fail it
        event = AgentFailedEvent(
            agent_name="failing",
            agent_index=0,
            total_agents=3,
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
        """Test AgentFailedEvent for an agent that wasn't started."""
        event = AgentFailedEvent(
            agent_name="instant_fail",
            agent_index=0,
            total_agents=3,
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
        collector.handle(WorkflowStartEvent(workflow_name="test", agent_count=3))

        # Complete multiple agents with tokens
        for i, (name, tokens) in enumerate(
            [
                ("agent1", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}),
                ("agent2", {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}),
                ("agent3", {"prompt_tokens": 300, "completion_tokens": 150, "total_tokens": 450}),
            ]
        ):
            collector.handle(AgentStartEvent(agent_name=name, agent_index=i))
            collector.handle(
                AgentCompleteEvent(agent_name=name, agent_index=i, tokens=tokens)
            )

        assert collector._total_tokens["prompt_tokens"] == 600
        assert collector._total_tokens["completion_tokens"] == 300
        assert collector._total_tokens["total_tokens"] == 900


class TestFlushAndOutput:
    """Tests for flush and output generation."""

    def test_flush_creates_target_directory(self, collector, temp_output_dir):
        """Test that flush creates target directory."""
        collector.handle(WorkflowStartEvent(workflow_name="test", agent_count=0))
        collector.handle(WorkflowCompleteEvent(workflow_name="test"))

        assert (temp_output_dir / "target").exists()

    def test_flush_writes_run_results_json(self, collector, temp_output_dir):
        """Test that flush writes run_results.json."""
        collector.handle(WorkflowStartEvent(workflow_name="test", agent_count=1))
        collector.handle(AgentStartEvent(agent_name="agent1", agent_index=0))
        collector.handle(
            AgentCompleteEvent(
                agent_name="agent1",
                agent_index=0,
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
        collector.handle(
            WorkflowStartEvent(workflow_name="my_workflow", agent_count=2)
        )
        collector.handle(AgentStartEvent(agent_name="agent1", agent_index=0))
        collector.handle(
            AgentCompleteEvent(
                agent_name="agent1",
                agent_index=0,
                execution_time=5.0,
                tokens={"total_tokens": 100},
            )
        )
        collector.handle(
            AgentSkipEvent(agent_name="agent2", agent_index=1, skip_reason="cached")
        )
        collector.handle(
            WorkflowCompleteEvent(
                workflow_name="my_workflow",
                elapsed_time=5.0,
                agents_completed=1,
                agents_skipped=1,
            )
        )

        output_path = temp_output_dir / "target" / "run_results.json"
        with open(output_path) as f:
            data = json.load(f)

        # Check metadata
        assert data["metadata"]["workflow_name"] == "my_workflow"
        assert data["metadata"]["agent_count"] == 2
        assert data["metadata"]["status"] == "success"

        # Check results are sorted by agent_index
        assert len(data["results"]) == 2
        assert data["results"][0]["agent_name"] == "agent1"
        assert data["results"][1]["agent_name"] == "agent2"

    def test_flush_without_output_dir(self):
        """Test that flush does nothing without output_dir."""
        collector = RunResultsCollector()  # No output_dir
        collector.handle(WorkflowStartEvent(workflow_name="test", agent_count=0))

        # Should not raise
        collector.flush()

    def test_results_sorted_by_index(self, collector, temp_output_dir):
        """Test that results are sorted by agent_index in output."""
        collector.handle(WorkflowStartEvent(workflow_name="test", agent_count=3))

        # Add agents out of order
        for name, idx in [("third", 2), ("first", 0), ("second", 1)]:
            collector.handle(AgentStartEvent(agent_name=name, agent_index=idx))
            collector.handle(AgentCompleteEvent(agent_name=name, agent_index=idx))

        collector.handle(WorkflowCompleteEvent(workflow_name="test"))

        output_path = temp_output_dir / "target" / "run_results.json"
        with open(output_path) as f:
            data = json.load(f)

        indices = [r["agent_index"] for r in data["results"]]
        assert indices == [0, 1, 2]


class TestGetSummary:
    """Tests for get_summary method."""

    def test_get_summary_empty(self, collector):
        """Test summary with no results."""
        summary = collector.get_summary()

        assert summary["success"] == 0
        assert summary["skipped"] == 0
        assert summary["cached"] == 0
        assert summary["error"] == 0
        assert summary["running"] == 0

    def test_get_summary_with_results(self, collector):
        """Test summary with various result statuses."""
        collector.handle(WorkflowStartEvent(workflow_name="test", agent_count=5))

        # Add various result types
        collector.handle(AgentStartEvent(agent_name="success1", agent_index=0))
        collector.handle(AgentCompleteEvent(agent_name="success1", agent_index=0))

        collector.handle(AgentStartEvent(agent_name="success2", agent_index=1))
        collector.handle(AgentCompleteEvent(agent_name="success2", agent_index=1))

        collector.handle(AgentSkipEvent(agent_name="skipped1", agent_index=2))

        collector.handle(AgentCachedEvent(agent_name="cached1", agent_index=3))

        collector.handle(AgentStartEvent(agent_name="failed1", agent_index=4))
        collector.handle(
            AgentFailedEvent(
                agent_name="failed1", agent_index=4, error_message="Error"
            )
        )

        summary = collector.get_summary()

        assert summary["success"] == 2
        assert summary["skipped"] == 1
        assert summary["cached"] == 1
        assert summary["error"] == 1


class TestUniqueIdGeneration:
    """Tests for unique_id generation in results."""

    def test_unique_id_format(self, collector):
        """Test that unique_id follows workflow.agent_name format."""
        collector.handle(WorkflowStartEvent(workflow_name="my_workflow", agent_count=1))
        collector.handle(AgentStartEvent(agent_name="my_agent", agent_index=0))

        result = collector._results["my_agent"]
        assert result.unique_id == "my_workflow.my_agent"

    def test_unique_id_updates_with_workflow(self, collector):
        """Test that unique_id uses workflow name from start event."""
        # Handle workflow start which sets the workflow_name
        collector.handle(
            WorkflowStartEvent(workflow_name="actual_workflow", agent_count=1)
        )
        collector.handle(AgentStartEvent(agent_name="agent", agent_index=0))

        result = collector._results["agent"]
        assert result.unique_id == "actual_workflow.agent"
