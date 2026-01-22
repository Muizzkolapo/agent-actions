"""Tests for LoggingBridgeHandler.

This module tests:
- Python logging to event conversion
- Log level mapping
- Category extraction from logger names
- LogEvent, DebugEvent, SystemEvent types
- Exception info handling
"""

import logging
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel, EventMeta
from agent_actions.logging.core.handlers.bridge import (
    LoggingBridgeHandler,
    LogEvent,
    DebugEvent,
    SystemEvent,
)
from agent_actions.logging.core.manager import EventManager


@pytest.fixture(autouse=True)
def reset_event_manager():
    """Reset EventManager singleton before and after each test."""
    EventManager.reset()
    yield
    EventManager.reset()


class MockEventCapture:
    """Captures events fired to the EventManager."""

    def __init__(self):
        self.events: list[BaseEvent] = []

    def handle(self, event: BaseEvent) -> None:
        self.events.append(event)

    def accepts(self, event: BaseEvent) -> bool:
        return True

    def flush(self) -> None:
        pass


class TestLogEventType:
    """Tests for LogEvent dataclass."""

    def test_log_event_defaults(self):
        """Test LogEvent default values."""
        event = LogEvent(message="test")

        assert event.logger_name == ""
        assert event.source_file == ""
        assert event.source_line == 0
        assert event.func_name == ""
        assert event.exc_info is None

    def test_log_event_default_category(self):
        """Test LogEvent default category.

        Note: LogEvent inherits from BaseEvent which defaults category to "system".
        The LogEvent.__post_init__ only sets category to "log" if it's empty/falsy.
        Since BaseEvent provides "system" as default, that takes precedence.
        """
        event = LogEvent(message="test")
        # BaseEvent's default category is "system", which is truthy,
        # so LogEvent's __post_init__ doesn't override it
        assert event.category == "system"

    def test_log_event_category_set_to_log_when_empty(self):
        """Test LogEvent sets category to 'log' when explicitly empty."""
        event = LogEvent(message="test", category="")
        assert event.category == "log"

    def test_log_event_preserves_category(self):
        """Test LogEvent preserves explicitly set category."""
        event = LogEvent(message="test", category="workflow")
        assert event.category == "workflow"

    def test_log_event_code_generation(self):
        """Test LogEvent code generation based on logger name."""
        event = LogEvent(message="test", logger_name="agent_actions.workflow")
        code = event.code

        assert code.startswith("X")
        assert len(code) == 4

    def test_log_event_code_consistent(self):
        """Test that same logger name produces same code."""
        event1 = LogEvent(message="test1", logger_name="agent_actions.test")
        event2 = LogEvent(message="test2", logger_name="agent_actions.test")

        assert event1.code == event2.code

    def test_log_event_has_exception_false(self):
        """Test has_exception returns False when no exception."""
        event = LogEvent(message="test")
        assert event.has_exception is False

    def test_log_event_has_exception_true(self):
        """Test has_exception returns True when exception present."""
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            event = LogEvent(message="test", exc_info=sys.exc_info())
            assert event.has_exception is True


class TestDebugEventType:
    """Tests for DebugEvent dataclass."""

    def test_debug_event_level(self):
        """Test DebugEvent has DEBUG level."""
        event = DebugEvent(message="test")
        assert event.level == EventLevel.DEBUG

    def test_debug_event_category(self):
        """Test DebugEvent has debug category."""
        event = DebugEvent(message="test")
        assert event.category == "debug"

    def test_debug_event_code(self):
        """Test DebugEvent code is X001."""
        event = DebugEvent(message="test")
        assert event.code == "X001"

    def test_debug_event_fields(self):
        """Test DebugEvent custom fields."""
        event = DebugEvent(message="test", module="my_module", detail="extra info")
        assert event.module == "my_module"
        assert event.detail == "extra info"


class TestSystemEventType:
    """Tests for SystemEvent dataclass."""

    def test_system_event_default_level(self):
        """Test SystemEvent default level is INFO."""
        event = SystemEvent(message="test")
        assert event.level == EventLevel.INFO

    def test_system_event_preserves_level(self):
        """Test SystemEvent preserves explicitly set level."""
        event = SystemEvent(level=EventLevel.WARN, message="test")
        assert event.level == EventLevel.WARN

    def test_system_event_category(self):
        """Test SystemEvent has system category."""
        event = SystemEvent(message="test")
        assert event.category == "system"

    def test_system_event_code(self):
        """Test SystemEvent code is X002."""
        event = SystemEvent(message="test")
        assert event.code == "X002"

    def test_system_event_fields(self):
        """Test SystemEvent custom fields."""
        event = SystemEvent(message="test", operation="startup", detail="initializing")
        assert event.operation == "startup"
        assert event.detail == "initializing"


class TestLoggingBridgeHandlerInit:
    """Tests for LoggingBridgeHandler initialization."""

    def test_default_level(self):
        """Test default level is DEBUG."""
        handler = LoggingBridgeHandler()
        assert handler.level == logging.DEBUG

    def test_custom_level(self):
        """Test setting custom level."""
        handler = LoggingBridgeHandler(level=logging.INFO)
        assert handler.level == logging.INFO

    def test_event_manager_lazy_init(self):
        """Test event manager is lazily initialized."""
        handler = LoggingBridgeHandler()
        assert handler._event_manager is None


class TestLoggingBridgeHandlerEmit:
    """Tests for LoggingBridgeHandler.emit()."""

    def test_emit_fires_event(self):
        """Test that emit fires an event to EventManager."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("test.emit")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test message")

        assert len(capture.events) == 1
        assert capture.events[0].message == "Test message"

    def test_emit_creates_log_event(self):
        """Test that emit creates LogEvent type."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("test.log_event")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test message")

        event = capture.events[0]
        assert isinstance(event, LogEvent)
        assert event.logger_name == "test.log_event"

    def test_emit_level_mapping(self):
        """Test that Python log levels map to EventLevels."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("test.levels")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.debug("debug")
        logger.info("info")
        logger.warning("warning")
        logger.error("error")
        logger.critical("critical")

        levels = [e.level for e in capture.events]
        assert levels[0] == EventLevel.DEBUG
        assert levels[1] == EventLevel.INFO
        assert levels[2] == EventLevel.WARN
        assert levels[3] == EventLevel.ERROR
        assert levels[4] == EventLevel.ERROR  # CRITICAL maps to ERROR

    def test_emit_includes_source_info(self):
        """Test that emit includes source file/line info."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("test.source")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test message")  # Line number will be captured

        event = capture.events[0]
        assert isinstance(event, LogEvent)
        assert "test_logging_bridge.py" in event.source_file
        assert event.source_line > 0
        assert event.func_name == "test_emit_includes_source_info"


class TestCategoryExtraction:
    """Tests for category extraction from logger names."""

    def test_extract_category_from_agent_actions_logger(self):
        """Test category extraction from agent_actions.* loggers."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("agent_actions.workflow.coordinator")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test")

        assert capture.events[0].category == "workflow"

    def test_extract_category_from_non_agent_actions_logger(self):
        """Test category defaults to 'system' for non-agent_actions loggers."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("other.module")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test")

        assert capture.events[0].category == "system"

    def test_extract_category_from_short_logger_name(self):
        """Test category extraction with single-part logger name."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("simple")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test")

        assert capture.events[0].category == "system"

    def test_extract_category_various_modules(self):
        """Test category extraction for various module names."""
        handler = LoggingBridgeHandler()

        # Test the private method directly
        assert handler._extract_category("agent_actions.llm.provider") == "llm"
        assert handler._extract_category("agent_actions.batch.processor") == "batch"
        assert handler._extract_category("agent_actions.validation") == "validation"
        assert handler._extract_category("agent_actions") == "system"


class TestExtraFieldsCopying:
    """Tests for copying extra fields from log records."""

    def test_copy_operation_extra(self):
        """Test that 'operation' extra field is copied."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("test.extra")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test", extra={"operation": "fetch_data"})

        assert capture.events[0].data.get("operation") == "fetch_data"

    def test_copy_agent_name_extra(self):
        """Test that 'agent_name' extra field is copied."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("test.extra")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test", extra={"agent_name": "extract_data"})

        assert capture.events[0].data.get("agent_name") == "extract_data"

    def test_copy_workflow_name_extra(self):
        """Test that 'workflow_name' extra field is copied."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("test.extra")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("Test", extra={"workflow_name": "my_workflow"})

        assert capture.events[0].data.get("workflow_name") == "my_workflow"


class TestErrorHandling:
    """Tests for error handling in the bridge."""

    def test_emit_catches_exceptions(self):
        """Test that emit catches and handles exceptions gracefully."""
        handler = LoggingBridgeHandler()

        # Create a mock that raises an exception
        with patch.object(EventManager, "get") as mock_get:
            mock_manager = Mock()
            mock_manager.fire.side_effect = Exception("Fire failed")
            mock_get.return_value = mock_manager

            # Reset handler's cached manager
            handler._event_manager = None

            # Create a log record
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Test message",
                args=(),
                exc_info=None,
            )

            # Should not raise
            with patch.object(handler, "handleError"):
                handler.emit(record)

    def test_emit_with_exception_info(self):
        """Test emit with exception info in log record."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        logger = logging.getLogger("test.exception")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        try:
            raise ValueError("Test error")
        except ValueError:
            logger.exception("An error occurred")

        event = capture.events[0]
        assert isinstance(event, LogEvent)
        assert event.has_exception
        assert event.exc_info is not None


class TestEventManagerCaching:
    """Tests for EventManager caching in the bridge."""

    def test_event_manager_cached(self):
        """Test that EventManager is cached after first use."""
        capture = MockEventCapture()
        manager = EventManager.get()
        manager.register(capture)

        handler = LoggingBridgeHandler()
        assert handler._event_manager is None

        # First emit should cache the manager
        logger = logging.getLogger("test.cache")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.info("First message")
        assert handler._event_manager is not None

        # Second emit should use cached manager
        cached_manager = handler._event_manager
        logger.info("Second message")
        assert handler._event_manager is cached_manager
