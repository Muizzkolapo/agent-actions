"""Tests for EventManager and event dispatching."""

import threading
from typing import Any
from unittest.mock import Mock

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.core.manager import EventManager, fire_event
from agent_actions.logging.core.protocols import CategoryFilter, LevelFilter


@pytest.fixture(autouse=True)
def reset_event_manager():
    """Reset EventManager singleton before and after each test."""
    EventManager.reset()
    yield
    EventManager.reset()


class MockHandler:
    """Mock event handler for testing."""

    def __init__(self, accept_all: bool = True, min_level: EventLevel = None):
        self.events_received: list[BaseEvent] = []
        self.accept_all = accept_all
        self.min_level = min_level
        self.flushed = False

    def handle(self, event: BaseEvent) -> None:
        self.events_received.append(event)

    def accepts(self, event: BaseEvent) -> bool:
        if self.min_level:
            level_order = [EventLevel.DEBUG, EventLevel.INFO, EventLevel.WARN, EventLevel.ERROR]
            if level_order.index(event.level) < level_order.index(self.min_level):
                return False
        return self.accept_all

    def flush(self) -> None:
        self.flushed = True


class TestEventDispatching:
    """Tests for event dispatching to handlers."""

    def test_fire_event_to_handler(self):
        """Test that events are dispatched to handlers."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)

        event = BaseEvent(message="test event")
        manager.fire(event)

        assert len(handler.events_received) == 1
        assert handler.events_received[0] is event

    def test_fire_event_global_function(self):
        """Test fire_event() convenience function."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)

        event = BaseEvent(message="test event")
        fire_event(event)

        assert len(handler.events_received) == 1

    def test_handler_accepts_filter(self):
        """Test that handler.accepts() filters events."""
        manager = EventManager.get()
        handler = MockHandler(accept_all=False)
        manager.register(handler)

        event = BaseEvent(message="test event")
        manager.fire(event)

        assert len(handler.events_received) == 0

    def test_handler_level_filtering(self):
        """Test handler filtering by level."""
        manager = EventManager.get()
        handler = MockHandler(min_level=EventLevel.WARN)
        manager.register(handler)

        debug_event = BaseEvent(level=EventLevel.DEBUG, message="debug")
        info_event = BaseEvent(level=EventLevel.INFO, message="info")
        warn_event = BaseEvent(level=EventLevel.WARN, message="warn")
        error_event = BaseEvent(level=EventLevel.ERROR, message="error")

        manager.fire(debug_event)
        manager.fire(info_event)
        manager.fire(warn_event)
        manager.fire(error_event)

        assert len(handler.events_received) == 2
        assert handler.events_received[0].level == EventLevel.WARN
        assert handler.events_received[1].level == EventLevel.ERROR

    def test_multiple_handlers_receive_event(self):
        """Test that all handlers receive events."""
        manager = EventManager.get()
        handler1 = MockHandler()
        handler2 = MockHandler()
        manager.register(handler1)
        manager.register(handler2)

        event = BaseEvent(message="test event")
        manager.fire(event)

        assert len(handler1.events_received) == 1
        assert len(handler2.events_received) == 1

    def test_handler_error_does_not_break_dispatch(self):
        """Test that handler errors don't break event dispatch."""
        manager = EventManager.get()

        broken_handler = Mock()
        broken_handler.accepts.return_value = True
        broken_handler.handle.side_effect = Exception("Handler error")

        working_handler = MockHandler()

        manager.register(broken_handler)
        manager.register(working_handler)

        event = BaseEvent(message="test event")
        manager.fire(event)  # Should not raise

        assert len(working_handler.events_received) == 1


class TestContextManagement:
    """Tests for context management."""

    def test_set_context(self):
        """Test setting context values."""
        manager = EventManager.get()

        manager.set_context(invocation_id="inv-123", correlation_id="corr-456")

        assert manager.get_context("invocation_id") == "inv-123"
        assert manager.get_context("correlation_id") == "corr-456"

    def test_clear_context(self):
        """Test clearing context."""
        manager = EventManager.get()
        manager.set_context(key="value")

        manager.clear_context()

        assert manager.get_context("key") is None

    def test_context_injected_into_event(self):
        """Test that context is injected into event metadata."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)

        manager.set_context(invocation_id="inv-123", correlation_id="corr-456")

        event = BaseEvent(message="test")
        manager.fire(event)

        received = handler.events_received[0]
        assert received.meta.invocation_id == "inv-123"
        assert received.meta.correlation_id == "corr-456"

    def test_context_manager(self):
        """Test context() context manager."""
        manager = EventManager.get()
        manager.set_context(outer_key="outer_value")

        with manager.context(inner_key="inner_value"):
            assert manager.get_context("outer_key") == "outer_value"
            assert manager.get_context("inner_key") == "inner_value"

        assert manager.get_context("outer_key") == "outer_value"
        assert manager.get_context("inner_key") is None

    def test_nested_context_managers(self):
        """Test nested context() managers."""
        manager = EventManager.get()

        manager.set_context(level="0")

        with manager.context(level="1"):
            assert manager.get_context("level") == "1"

            with manager.context(level="2"):
                assert manager.get_context("level") == "2"

            assert manager.get_context("level") == "1"

        assert manager.get_context("level") == "0"


class TestGlobalFilters:
    """Tests for global event filters."""

    def test_level_filter_drops_events(self):
        """Test that LevelFilter drops events below threshold."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)
        manager.add_filter(LevelFilter(EventLevel.WARN))

        debug_event = BaseEvent(level=EventLevel.DEBUG, message="debug")
        info_event = BaseEvent(level=EventLevel.INFO, message="info")
        warn_event = BaseEvent(level=EventLevel.WARN, message="warn")

        manager.fire(debug_event)
        manager.fire(info_event)
        manager.fire(warn_event)

        assert len(handler.events_received) == 1
        assert handler.events_received[0].level == EventLevel.WARN

    def test_category_filter(self):
        """Test CategoryFilter filters by category."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)
        manager.add_filter(CategoryFilter({"workflow", "agent"}))

        workflow_event = BaseEvent(category="workflow", message="workflow")
        agent_event = BaseEvent(category="agent", message="agent")
        batch_event = BaseEvent(category="batch", message="batch")

        manager.fire(workflow_event)
        manager.fire(agent_event)
        manager.fire(batch_event)

        assert len(handler.events_received) == 2
        categories = [e.category for e in handler.events_received]
        assert "workflow" in categories
        assert "agent" in categories

    def test_multiple_filters_chain(self):
        """Test that multiple filters are chained."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)

        # First filter passes only INFO+
        manager.add_filter(LevelFilter(EventLevel.INFO))
        # Second filter passes only workflow category
        manager.add_filter(CategoryFilter({"workflow"}))

        # These should pass both filters
        workflow_info = BaseEvent(level=EventLevel.INFO, category="workflow", message="pass")

        # These should fail one or both
        workflow_debug = BaseEvent(level=EventLevel.DEBUG, category="workflow", message="fail")
        agent_info = BaseEvent(level=EventLevel.INFO, category="agent", message="fail")

        manager.fire(workflow_info)
        manager.fire(workflow_debug)
        manager.fire(agent_info)

        assert len(handler.events_received) == 1


class TestFlush:
    """Tests for flush functionality."""

    def test_flush_calls_handler_flush(self):
        """Test that flush() calls flush on all handlers."""
        manager = EventManager.get()
        handler1 = MockHandler()
        handler2 = MockHandler()
        manager.register(handler1)
        manager.register(handler2)

        manager.flush()

        assert handler1.flushed
        assert handler2.flushed

    def test_flush_error_does_not_break(self):
        """Test that flush errors don't break flush for other handlers."""
        manager = EventManager.get()

        broken_handler = Mock()
        broken_handler.flush.side_effect = Exception("Flush error")

        working_handler = MockHandler()

        manager.register(broken_handler)
        manager.register(working_handler)

        manager.flush()  # Should not raise

        assert working_handler.flushed


class TestResetBehavior:
    """Tests for reset behavior."""

    def test_reset_clears_handlers(self):
        """Test that reset clears all handlers."""
        manager = EventManager.get()
        manager.register(MockHandler())
        manager.register(MockHandler())

        EventManager.reset()

        new_manager = EventManager.get()
        assert len(new_manager._handlers) == 0

    def test_reset_clears_context(self):
        """Test that reset clears context."""
        manager = EventManager.get()
        manager.set_context(key="value")

        EventManager.reset()

        new_manager = EventManager.get()
        assert new_manager.get_context("key") is None

    def test_reset_flushes_handlers(self):
        """Test that reset flushes handlers before clearing."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)

        EventManager.reset()

        assert handler.flushed


class TestBaseEventCodeFallback:
    """Tests for BaseEvent.code default (1-C)."""

    def test_base_event_code_returns_static_fallback(self):
        """BaseEvent.code returns a fixed fallback since all subclasses override."""
        event = BaseEvent(category="workflow", message="test")
        assert event.code == "X000"


class TestAtexitAccumulation:
    """Tests for atexit callback accumulation fix (1-E)."""

    def test_reset_and_get_does_not_duplicate_atexit(self):
        """Multiple reset()+get() cycles should not accumulate atexit callbacks."""
        import agent_actions.logging.core.manager as mgr

        # After the first get() in the fixture, _atexit_registered is True
        assert mgr._atexit_registered is True

        EventManager.reset()
        EventManager.get()
        EventManager.reset()
        EventManager.get()

        # Still True, but only registered once
        assert mgr._atexit_registered is True


class TestThreadSafety:
    """Tests for thread-safe context and handler iteration (1-D, 2-B)."""

    def test_concurrent_fire_and_register(self):
        """fire() and register() can run concurrently without error."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)

        errors = []

        def fire_many():
            try:
                for _ in range(50):
                    manager.fire(BaseEvent(message="concurrent"))
            except Exception as exc:
                errors.append(exc)

        def register_many():
            try:
                for _ in range(50):
                    manager.register(MockHandler())
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=fire_many)
        t2 = threading.Thread(target=register_many)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == []

    def test_overlapping_thread_contexts_are_isolated(self):
        """Two threads with overlapping context() blocks don't clobber each other."""
        manager = EventManager.get()
        manager.set_context(base="shared")

        barrier = threading.Barrier(2)
        results: dict[str, Any] = {}

        def thread_a():
            with manager.context(a="1"):
                barrier.wait()  # Ensure both threads are inside context()
                import time

                time.sleep(0.02)  # Let thread_b exit its context()
                results["a_inside"] = manager.get_context("a")
                results["a_sees_b"] = manager.get_context("b")
            results["a_after"] = manager.get_context("a")

        def thread_b():
            with manager.context(b="2"):
                barrier.wait()
                results["b_inside"] = manager.get_context("b")
                results["b_sees_a"] = manager.get_context("a")
            results["b_after"] = manager.get_context("b")

        t1 = threading.Thread(target=thread_a)
        t2 = threading.Thread(target=thread_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Each thread sees its own overlay, not the other's
        assert results["a_inside"] == "1"
        assert results["b_inside"] == "2"
        assert results["a_sees_b"] is None  # Thread A shouldn't see b
        assert results["b_sees_a"] is None  # Thread B shouldn't see a
        # After exiting context(), overlay values are gone
        assert results["a_after"] is None
        assert results["b_after"] is None
        # Global context survives
        assert manager.get_context("base") == "shared"

    def test_concurrent_fire_and_set_context(self):
        """fire() and set_context() can run concurrently without error."""
        manager = EventManager.get()
        handler = MockHandler()
        manager.register(handler)

        errors = []

        def fire_many():
            try:
                for _ in range(50):
                    manager.fire(BaseEvent(message="ctx"))
            except Exception as exc:
                errors.append(exc)

        def set_ctx():
            try:
                for i in range(50):
                    manager.set_context(key=str(i))
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=fire_many)
        t2 = threading.Thread(target=set_ctx)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == []
