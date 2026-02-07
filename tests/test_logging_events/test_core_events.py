"""Tests for core event types and infrastructure.

This module tests:
- EventLevel enum and level mapping
- EventCategory enum
- EventMeta dataclass and serialization
- BaseEvent dataclass and behavior
- Domain-specific events (WorkflowStartEvent, AgentCompleteEvent, etc.)
"""

from datetime import datetime, timezone
from dataclasses import dataclass

from agent_actions.logging.core.events import (
    BaseEvent,
    EventLevel,
    EventCategory,
    EventMeta,
)
from agent_actions.logging.events.types import (
    EventCategories,
    WorkflowStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    AgentStartEvent,
    AgentCompleteEvent,
    AgentSkipEvent,
    AgentFailedEvent,
    AgentCachedEvent,
    BatchSubmittedEvent,
    BatchProgressEvent,
    BatchCompleteEvent,
    LLMRequestEvent,
    LLMResponseEvent,
    LLMErrorEvent,
    RateLimitEvent,
)


class TestEventLevel:
    """Tests for EventLevel enum."""

    def test_event_level_values(self):
        """Test EventLevel enum has correct string values."""
        assert EventLevel.DEBUG.value == "debug"
        assert EventLevel.INFO.value == "info"
        assert EventLevel.WARN.value == "warn"
        assert EventLevel.ERROR.value == "error"

    def test_log_level_mapping(self):
        """Test mapping to Python logging levels."""
        import logging

        assert EventLevel.DEBUG.log_level == logging.DEBUG
        assert EventLevel.INFO.log_level == logging.INFO
        assert EventLevel.WARN.log_level == logging.WARNING
        assert EventLevel.ERROR.log_level == logging.ERROR

    def test_event_level_comparison(self):
        """Test that event levels can be compared via log_level property."""
        assert EventLevel.DEBUG.log_level < EventLevel.INFO.log_level
        assert EventLevel.INFO.log_level < EventLevel.WARN.log_level
        assert EventLevel.WARN.log_level < EventLevel.ERROR.log_level


class TestEventCategory:
    """Tests for EventCategory enum."""

    def test_event_category_values(self):
        """Test EventCategory enum has correct string values."""
        assert EventCategory.SYSTEM.value == "system"
        assert EventCategory.LIFECYCLE.value == "lifecycle"
        assert EventCategory.OPERATION.value == "operation"
        assert EventCategory.ERROR.value == "error"


class TestEventMeta:
    """Tests for EventMeta dataclass."""

    def test_default_timestamp(self):
        """Test that timestamp defaults to current UTC time."""
        before = datetime.now(timezone.utc)
        meta = EventMeta()
        after = datetime.now(timezone.utc)

        assert before <= meta.timestamp <= after
        assert meta.timestamp.tzinfo == timezone.utc

    def test_default_fields(self):
        """Test that optional fields default to None/empty."""
        meta = EventMeta()
        assert meta.correlation_id is None
        assert meta.invocation_id is None
        assert meta.thread_id is None
        assert meta.extra == {}

    def test_custom_fields(self):
        """Test setting custom field values."""
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        meta = EventMeta(
            timestamp=ts,
            correlation_id="corr-123",
            invocation_id="inv-456",
            thread_id="thread-789",
            extra={"key": "value"},
        )

        assert meta.timestamp == ts
        assert meta.correlation_id == "corr-123"
        assert meta.invocation_id == "inv-456"
        assert meta.thread_id == "thread-789"
        assert meta.extra == {"key": "value"}

    def test_to_dict(self):
        """Test serialization to dictionary."""
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        meta = EventMeta(
            timestamp=ts,
            correlation_id="corr-123",
            invocation_id="inv-456",
            thread_id="thread-789",
            extra={"custom_key": "custom_value"},
        )

        d = meta.to_dict()

        assert d["timestamp"] == "2024-01-15T10:30:00+00:00"
        assert d["correlation_id"] == "corr-123"
        assert d["invocation_id"] == "inv-456"
        assert d["thread_id"] == "thread-789"
        assert d["custom_key"] == "custom_value"

    def test_to_dict_includes_extra(self):
        """Test that extra fields are merged into output dict."""
        meta = EventMeta(extra={"workflow_name": "test", "agent_count": 5})
        d = meta.to_dict()

        assert d["workflow_name"] == "test"
        assert d["agent_count"] == 5


class TestBaseEvent:
    """Tests for BaseEvent dataclass."""

    def test_base_event_defaults(self):
        """Test BaseEvent has correct defaults."""
        event = BaseEvent(message="test message")

        assert event.level == EventLevel.INFO
        assert event.category == "system"
        assert event.message == "test message"
        assert event.data == {}
        assert event.meta is not None
        assert event.meta.timestamp is not None

    def test_base_event_event_type(self):
        """Test event_type returns class name."""
        event = BaseEvent(message="test")
        assert event.event_type == "BaseEvent"

    def test_base_event_code_generation(self):
        """Test default code generation."""
        event = BaseEvent(message="test", category="workflow")
        code = event.code

        # Code should start with category first letter
        assert code.startswith("W")
        # Code should be 4 characters (letter + 3 digits)
        assert len(code) == 4

    def test_base_event_code_default_category(self):
        """Test code generation with default system category."""
        event = BaseEvent(message="test")
        code = event.code

        assert code.startswith("S")  # 'system' starts with 's'

    def test_base_event_to_dict(self):
        """Test serialization to dictionary."""
        event = BaseEvent(
            level=EventLevel.WARN,
            category="test_category",
            message="test message",
            data={"key": "value"},
        )

        d = event.to_dict()

        assert d["event_type"] == "BaseEvent"
        assert d["code"] is not None
        assert d["level"] == "warn"
        assert d["category"] == "test_category"
        assert d["message"] == "test message"
        assert d["data"] == {"key": "value"}
        assert "meta" in d
        assert "timestamp" in d["meta"]

    def test_custom_event_inherits_behavior(self):
        """Test that custom events inherit BaseEvent behavior."""

        @dataclass
        class CustomEvent(BaseEvent):
            custom_field: str = ""

            def __post_init__(self):
                self.level = EventLevel.DEBUG
                self.category = "custom"
                self.message = f"Custom: {self.custom_field}"

            @property
            def code(self):
                return "X999"

        event = CustomEvent(custom_field="test_value")

        assert event.level == EventLevel.DEBUG
        assert event.category == "custom"
        assert event.message == "Custom: test_value"
        assert event.code == "X999"
        assert event.event_type == "CustomEvent"


class TestEventCategories:
    """Tests for EventCategories constants."""

    def test_event_categories(self):
        """Test EventCategories has expected values."""
        assert EventCategories.WORKFLOW == "workflow"
        assert EventCategories.AGENT == "agent"
        assert EventCategories.BATCH == "batch"
        assert EventCategories.LLM == "llm"
        assert EventCategories.VALIDATION == "validation"


class TestWorkflowEvents:
    """Tests for workflow lifecycle events."""

    def test_workflow_start_event(self):
        """Test WorkflowStartEvent initialization and properties."""
        event = WorkflowStartEvent(
            workflow_name="test_workflow",
            agent_count=5,
            execution_mode="parallel",
            run_upstream=True,
            run_downstream=False,
        )

        assert event.level == EventLevel.INFO
        assert event.category == EventCategories.WORKFLOW
        assert event.code == "W001"
        assert "test_workflow" in event.message
        assert "5 agents" in event.message
        assert event.data["workflow_name"] == "test_workflow"
        assert event.data["agent_count"] == 5
        assert event.data["execution_mode"] == "parallel"
        assert event.data["run_upstream"] is True
        assert event.data["run_downstream"] is False

    def test_workflow_complete_event(self):
        """Test WorkflowCompleteEvent initialization and properties."""
        event = WorkflowCompleteEvent(
            workflow_name="test_workflow",
            elapsed_time=123.45,
            agents_completed=4,
            agents_skipped=1,
            agents_failed=0,
            total_tokens=5000,
        )

        assert event.level == EventLevel.INFO
        assert event.category == EventCategories.WORKFLOW
        assert event.code == "W002"
        assert "test_workflow" in event.message
        assert "123.45" in event.message
        assert "4 completed" in event.message
        assert event.data["elapsed_time"] == 123.45
        assert event.data["total_tokens"] == 5000

    def test_workflow_failed_event(self):
        """Test WorkflowFailedEvent initialization and properties."""
        event = WorkflowFailedEvent(
            workflow_name="test_workflow",
            error_message="Connection timeout",
            error_type="TimeoutError",
            elapsed_time=10.5,
            failed_agent="extract_data",
        )

        assert event.level == EventLevel.ERROR
        assert event.category == EventCategories.WORKFLOW
        assert event.code == "W003"
        assert "test_workflow" in event.message
        assert "Connection timeout" in event.message
        assert event.data["error_type"] == "TimeoutError"
        assert event.data["failed_agent"] == "extract_data"


class TestAgentEvents:
    """Tests for agent execution events."""

    def test_agent_start_event(self):
        """Test AgentStartEvent initialization and properties."""
        event = AgentStartEvent(
            agent_name="extract_data",
            agent_index=0,
            total_agents=5,
            agent_type="extractor",
            input_path="/data/input.json",
        )

        assert event.level == EventLevel.INFO
        assert event.category == EventCategories.AGENT
        assert event.code == "A001"
        assert "1/5" in event.message  # Index 0 shows as 1/5
        assert "START" in event.message
        assert "extract_data" in event.message
        assert event.data["agent_type"] == "extractor"

    def test_agent_complete_event(self):
        """Test AgentCompleteEvent initialization and properties."""
        event = AgentCompleteEvent(
            agent_name="transform",
            agent_index=1,
            total_agents=5,
            execution_time=12.34,
            output_path="/data/output.json",
            record_count=100,
            tokens={"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
        )

        assert event.level == EventLevel.INFO
        assert event.category == EventCategories.AGENT
        assert event.code == "A002"
        assert "2/5" in event.message  # Index 1 shows as 2/5
        assert "OK" in event.message
        assert "12.34" in event.message
        assert "700 tokens" in event.message
        assert event.data["tokens"]["total_tokens"] == 700

    def test_agent_skip_event(self):
        """Test AgentSkipEvent initialization and properties."""
        event = AgentSkipEvent(
            agent_name="transform",
            agent_index=1,
            total_agents=5,
            skip_reason="already completed",
        )

        assert event.level == EventLevel.INFO
        assert event.category == EventCategories.AGENT
        assert event.code == "A003"
        assert "SKIP" in event.message
        assert "already completed" in event.message

    def test_agent_failed_event(self):
        """Test AgentFailedEvent initialization and properties."""
        event = AgentFailedEvent(
            agent_name="load",
            agent_index=2,
            total_agents=5,
            error_message="Database connection failed",
            error_type="ConnectionError",
            execution_time=5.0,
            suggestion="Check database credentials",
        )

        assert event.level == EventLevel.ERROR
        assert event.category == EventCategories.AGENT
        assert event.code == "A004"
        assert "ERROR" in event.message
        assert "Database connection failed" in event.message
        assert event.data["suggestion"] == "Check database credentials"

    def test_agent_cached_event(self):
        """Test AgentCachedEvent initialization and properties."""
        event = AgentCachedEvent(
            agent_name="transform",
            agent_index=1,
            total_agents=5,
            cache_key="abc123",
        )

        assert event.level == EventLevel.INFO
        assert event.category == EventCategories.AGENT
        assert event.code == "A005"
        assert "CACHED" in event.message
        assert event.data["cache_key"] == "abc123"


class TestBatchEvents:
    """Tests for batch processing events."""

    def test_batch_submitted_event(self):
        """Test BatchSubmittedEvent initialization and properties."""
        event = BatchSubmittedEvent(
            batch_id="batch-001",
            agent_name="transform",
            request_count=100,
            provider="openai",
        )

        assert event.level == EventLevel.INFO
        assert event.category == EventCategories.BATCH
        assert event.code == "B001"
        assert "batch-001" in event.message
        assert "100 requests" in event.message
        assert "openai" in event.message

    def test_batch_progress_event(self):
        """Test BatchProgressEvent initialization and properties."""
        event = BatchProgressEvent(
            batch_id="batch-001",
            completed=50,
            total=100,
            failed=2,
        )

        assert event.level == EventLevel.DEBUG
        assert event.category == EventCategories.BATCH
        assert event.code == "B002"
        assert "50/100" in event.message
        assert "50.0%" in event.message
        assert event.data["percentage"] == 50.0

    def test_batch_complete_event(self):
        """Test BatchCompleteEvent initialization and properties."""
        event = BatchCompleteEvent(
            batch_id="batch-001",
            agent_name="transform",
            completed=98,
            failed=2,
            elapsed_time=300.5,
            total_tokens=50000,
        )

        assert event.level == EventLevel.INFO
        assert event.category == EventCategories.BATCH
        assert event.code == "B003"
        assert "2 failed" in event.message

    def test_batch_complete_event_success(self):
        """Test BatchCompleteEvent with no failures."""
        event = BatchCompleteEvent(
            batch_id="batch-001",
            agent_name="transform",
            completed=100,
            failed=0,
            elapsed_time=300.5,
            total_tokens=50000,
        )

        assert event.completed == 100
        assert event.failed == 0


class TestLLMEvents:
    """Tests for LLM interaction events."""

    def test_llm_request_event(self):
        """Test LLMRequestEvent initialization and properties."""
        event = LLMRequestEvent(
            provider="openai",
            model="gpt-4",
            agent_name="transform",
            prompt_tokens=500,
            request_id="req-123",
        )

        assert event.level == EventLevel.DEBUG
        assert event.category == EventCategories.LLM
        assert event.code == "L001"
        assert "openai/gpt-4" in event.message
        assert "500 prompt tokens" in event.message

    def test_llm_response_event(self):
        """Test LLMResponseEvent initialization and properties."""
        event = LLMResponseEvent(
            provider="openai",
            model="gpt-4",
            agent_name="transform",
            prompt_tokens=500,
            completion_tokens=200,
            total_tokens=700,
            latency_ms=1500.0,
            request_id="req-123",
        )

        assert event.level == EventLevel.DEBUG
        assert event.category == EventCategories.LLM
        assert event.code == "L002"
        assert "700 tokens" in event.message
        assert "1500ms" in event.message

    def test_llm_error_event(self):
        """Test LLMErrorEvent initialization and properties."""
        event = LLMErrorEvent(
            provider="openai",
            model="gpt-4",
            agent_name="transform",
            error_message="Rate limit exceeded",
            error_type="RateLimitError",
            retry_count=3,
            request_id="req-123",
        )

        assert event.level == EventLevel.ERROR
        assert event.category == EventCategories.LLM
        assert event.code == "L003"
        assert "Rate limit exceeded" in event.message
        assert event.data["retry_count"] == 3

    def test_rate_limit_event(self):
        """Test RateLimitEvent initialization and properties."""
        event = RateLimitEvent(
            provider="openai",
            retry_after=30.0,
            agent_name="transform",
            request_id="req-123",
        )

        assert event.level == EventLevel.WARN
        assert event.category == EventCategories.LLM
        assert event.code == "L004"
        assert "Rate limit hit" in event.message
        assert "30.0s" in event.message


class TestEventSerialization:
    """Tests for event serialization."""

    def test_event_roundtrip(self):
        """Test that events can be serialized and contain all expected fields."""
        event = WorkflowStartEvent(
            workflow_name="test",
            agent_count=3,
        )

        d = event.to_dict()

        assert d["event_type"] == "WorkflowStartEvent"
        assert d["code"] == "W001"
        assert d["level"] == "info"
        assert d["category"] == "workflow"
        assert "test" in d["message"]
        assert d["data"]["workflow_name"] == "test"
        assert d["data"]["agent_count"] == 3
        assert "timestamp" in d["meta"]

    def test_all_events_serializable(self):
        """Test that all event types can be serialized to dict."""
        import json

        events = [
            WorkflowStartEvent(workflow_name="test", agent_count=1),
            WorkflowCompleteEvent(workflow_name="test"),
            AgentCompleteEvent(
                agent_name="test",
                tokens={"prompt_tokens": 100, "total_tokens": 100},
            ),
            BatchProgressEvent(batch_id="test", completed=5, total=10),
        ]

        for event in events:
            d = event.to_dict()
            # Should be JSON serializable
            json_str = json.dumps(d, default=str)
            assert json_str is not None
