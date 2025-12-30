"""Tests for CorrelationContext and ExecutionContext."""

import pytest
from concurrent.futures import ThreadPoolExecutor
import asyncio

from agent_actions.logging.context import CorrelationContext, ExecutionContext


class TestExecutionContext:
    """Tests for ExecutionContext dataclass."""

    def test_creation_with_required_fields(self):
        """Test creating ExecutionContext with only required fields."""
        ctx = ExecutionContext(correlation_id="abc123")
        assert ctx.correlation_id == "abc123"
        assert ctx.workflow_name is None
        assert ctx.agent_name is None
        assert ctx.agent_index is None
        assert ctx.batch_id is None
        assert ctx.item_id is None
        assert ctx.extra == {}

    def test_creation_with_all_fields(self):
        """Test creating ExecutionContext with all fields."""
        ctx = ExecutionContext(
            correlation_id="abc123",
            workflow_name="test-workflow",
            agent_name="test-agent",
            agent_index=0,
            batch_id="batch-1",
            item_id="item-1",
            extra={"custom": "value"},
        )
        assert ctx.correlation_id == "abc123"
        assert ctx.workflow_name == "test-workflow"
        assert ctx.agent_name == "test-agent"
        assert ctx.agent_index == 0
        assert ctx.batch_id == "batch-1"
        assert ctx.item_id == "item-1"
        assert ctx.extra == {"custom": "value"}


class TestCorrelationContext:
    """Tests for CorrelationContext class."""

    def setup_method(self):
        """Clear context before each test."""
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clear context after each test."""
        CorrelationContext.clear_context()

    def test_generate_correlation_id_uniqueness(self):
        """Test that generated correlation IDs are unique."""
        ids = [CorrelationContext.generate_correlation_id() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_generate_correlation_id_length(self):
        """Test that correlation IDs are 8 characters."""
        cid = CorrelationContext.generate_correlation_id()
        assert len(cid) == 8

    def test_get_context_returns_none_when_not_set(self):
        """Test that get_context returns None when no context is set."""
        ctx = CorrelationContext.get_context()
        assert ctx is None

    def test_set_and_get_context(self):
        """Test setting and getting context."""
        ctx = ExecutionContext(correlation_id="test123", workflow_name="my-workflow")
        CorrelationContext.set_context(ctx)

        retrieved = CorrelationContext.get_context()
        assert retrieved is ctx
        assert retrieved.correlation_id == "test123"
        assert retrieved.workflow_name == "my-workflow"

    def test_clear_context(self):
        """Test clearing context."""
        ctx = ExecutionContext(correlation_id="test123")
        CorrelationContext.set_context(ctx)

        assert CorrelationContext.get_context() is not None

        CorrelationContext.clear_context()

        assert CorrelationContext.get_context() is None

    def test_start_workflow_creates_context(self):
        """Test that start_workflow creates and sets context."""
        ctx = CorrelationContext.start_workflow("my-workflow")

        assert ctx.correlation_id is not None
        assert len(ctx.correlation_id) == 8
        assert ctx.workflow_name == "my-workflow"

        # Verify it's set as current context
        current = CorrelationContext.get_context()
        assert current is ctx

    def test_set_agent_updates_context(self):
        """Test that set_agent updates the current context."""
        CorrelationContext.start_workflow("my-workflow")
        CorrelationContext.set_agent("agent-1", 0)

        ctx = CorrelationContext.get_context()
        assert ctx.agent_name == "agent-1"
        assert ctx.agent_index == 0

    def test_set_agent_without_context_is_safe(self):
        """Test that set_agent is safe when no context exists."""
        # Should not raise
        CorrelationContext.set_agent("agent-1", 0)

        ctx = CorrelationContext.get_context()
        assert ctx is None

    def test_set_batch_updates_context(self):
        """Test that set_batch updates the current context."""
        CorrelationContext.start_workflow("my-workflow")
        CorrelationContext.set_batch("batch-123")

        ctx = CorrelationContext.get_context()
        assert ctx.batch_id == "batch-123"

    def test_set_batch_without_context_is_safe(self):
        """Test that set_batch is safe when no context exists."""
        # Should not raise
        CorrelationContext.set_batch("batch-123")

        ctx = CorrelationContext.get_context()
        assert ctx is None

    def test_set_item_updates_context(self):
        """Test that set_item updates the current context."""
        CorrelationContext.start_workflow("my-workflow")
        CorrelationContext.set_item("item-456")

        ctx = CorrelationContext.get_context()
        assert ctx.item_id == "item-456"

    def test_set_item_without_context_is_safe(self):
        """Test that set_item is safe when no context exists."""
        # Should not raise
        CorrelationContext.set_item("item-456")

        ctx = CorrelationContext.get_context()
        assert ctx is None

    def test_add_extra_updates_context(self):
        """Test that add_extra adds to context extra dict."""
        CorrelationContext.start_workflow("my-workflow")
        CorrelationContext.add_extra("custom_field", "custom_value")

        ctx = CorrelationContext.get_context()
        assert ctx.extra["custom_field"] == "custom_value"

    def test_add_extra_without_context_is_safe(self):
        """Test that add_extra is safe when no context exists."""
        # Should not raise
        CorrelationContext.add_extra("custom_field", "custom_value")

        ctx = CorrelationContext.get_context()
        assert ctx is None

    def test_get_correlation_id_returns_id_when_set(self):
        """Test that get_correlation_id returns the ID when context is set."""
        ctx = CorrelationContext.start_workflow("my-workflow")

        cid = CorrelationContext.get_correlation_id()
        assert cid == ctx.correlation_id

    def test_get_correlation_id_returns_none_when_not_set(self):
        """Test that get_correlation_id returns None when no context."""
        cid = CorrelationContext.get_correlation_id()
        assert cid is None

    def test_context_updates_are_preserved(self):
        """Test that multiple updates are preserved in context."""
        ctx = CorrelationContext.start_workflow("my-workflow")
        CorrelationContext.set_agent("agent-1", 0)
        CorrelationContext.set_batch("batch-1")
        CorrelationContext.set_item("item-1")
        CorrelationContext.add_extra("key1", "value1")
        CorrelationContext.add_extra("key2", "value2")

        ctx = CorrelationContext.get_context()
        assert ctx.workflow_name == "my-workflow"
        assert ctx.agent_name == "agent-1"
        assert ctx.agent_index == 0
        assert ctx.batch_id == "batch-1"
        assert ctx.item_id == "item-1"
        assert ctx.extra == {"key1": "value1", "key2": "value2"}


class TestCorrelationContextThreadSafety:
    """Tests for CorrelationContext thread safety."""

    def setup_method(self):
        """Clear context before each test."""
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clear context after each test."""
        CorrelationContext.clear_context()

    def test_context_isolation_between_threads(self):
        """Test that context is isolated between threads."""
        results = {}

        def thread_work(thread_id: int):
            # Start workflow in this thread
            ctx = CorrelationContext.start_workflow(f"workflow-{thread_id}")
            CorrelationContext.set_agent(f"agent-{thread_id}", thread_id)

            # Store the context
            results[thread_id] = {
                "correlation_id": ctx.correlation_id,
                "workflow_name": CorrelationContext.get_context().workflow_name,
                "agent_name": CorrelationContext.get_context().agent_name,
            }

        # Run in multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(thread_work, i) for i in range(5)]
            for f in futures:
                f.result()

        # Verify each thread had its own context
        assert len(results) == 5
        for thread_id, result in results.items():
            assert result["workflow_name"] == f"workflow-{thread_id}"
            assert result["agent_name"] == f"agent-{thread_id}"

        # All correlation IDs should be unique
        correlation_ids = [r["correlation_id"] for r in results.values()]
        assert len(set(correlation_ids)) == 5


class TestCorrelationContextAsync:
    """Tests for CorrelationContext in async context."""

    def setup_method(self):
        """Clear context before each test."""
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clear context after each test."""
        CorrelationContext.clear_context()

    @pytest.mark.asyncio
    async def test_context_in_async_function(self):
        """Test that context works in async functions."""
        ctx = CorrelationContext.start_workflow("async-workflow")
        CorrelationContext.set_agent("async-agent", 0)

        # Simulate async work
        await asyncio.sleep(0.01)

        # Context should still be available
        current = CorrelationContext.get_context()
        assert current.correlation_id == ctx.correlation_id
        assert current.workflow_name == "async-workflow"
        assert current.agent_name == "async-agent"

    @pytest.mark.asyncio
    async def test_context_isolation_in_concurrent_tasks(self):
        """Test that context is isolated in concurrent async tasks."""
        results = {}

        async def async_work(task_id: int):
            ctx = CorrelationContext.start_workflow(f"workflow-{task_id}")
            CorrelationContext.set_agent(f"agent-{task_id}", task_id)

            # Simulate async work
            await asyncio.sleep(0.01)

            # Store context state
            current = CorrelationContext.get_context()
            results[task_id] = {
                "correlation_id": current.correlation_id,
                "workflow_name": current.workflow_name,
                "agent_name": current.agent_name,
            }

        # Run concurrent tasks
        await asyncio.gather(*[async_work(i) for i in range(5)])

        # Verify each task had its own context
        assert len(results) == 5
        for task_id, result in results.items():
            assert result["workflow_name"] == f"workflow-{task_id}"
            assert result["agent_name"] == f"agent-{task_id}"

        # All correlation IDs should be unique
        correlation_ids = [r["correlation_id"] for r in results.values()]
        assert len(set(correlation_ids)) == 5
