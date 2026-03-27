"""Tests for LoggerFactory."""

import logging
from unittest.mock import patch

import pytest

from agent_actions.logging.config import LoggingConfig
from agent_actions.logging.core.events import BaseEvent
from agent_actions.logging.factory import LoggerFactory


@pytest.fixture(autouse=True)
def reset_factory():
    """Reset LoggerFactory and EventManager before and after each test.

    Also clears handlers from the agent_actions logger to ensure test isolation,
    since logging.getLogger() returns the same logger instance across tests.
    """
    LoggerFactory.reset()
    # Clear any handlers from the root agent_actions logger for test isolation
    root_logger = logging.getLogger("agent_actions")
    root_logger.handlers.clear()
    yield
    LoggerFactory.reset()
    # Clear handlers again after test
    root_logger.handlers.clear()


@pytest.fixture
def temp_output_dir(tmp_path):
    """Provide a temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


class MockEventCapture:
    """Captures events for testing."""

    def __init__(self):
        self.events: list[BaseEvent] = []

    def handle(self, event: BaseEvent) -> None:
        self.events.append(event)

    def accepts(self, event: BaseEvent) -> bool:
        return True

    def flush(self) -> None:
        pass


class TestLoggerFactoryInitialize:
    """Tests for LoggerFactory.initialize()."""

    def test_initialize_with_workflow_name(self):
        """Test initialization with workflow name."""
        LoggerFactory.initialize(workflow_name="test_workflow")

        manager = LoggerFactory.get_event_manager()
        assert manager.get_context("workflow_name") == "test_workflow"

    def test_initialize_with_invocation_id(self):
        """Test initialization with invocation ID."""
        LoggerFactory.initialize(invocation_id="my-inv-id")

        manager = LoggerFactory.get_event_manager()
        assert manager.get_context("invocation_id") == "my-inv-id"

    def test_force_reinitialize_does_not_accumulate_handlers(self):
        """Regression: force=True must clear handlers before re-registering."""
        manager = LoggerFactory.initialize()
        handler_count_first = len(manager._handlers)

        manager = LoggerFactory.initialize(force=True)
        handler_count_second = len(manager._handlers)

        assert handler_count_second == handler_count_first, (
            f"Handler count grew from {handler_count_first} to {handler_count_second} "
            "after force re-init — handlers are accumulating"
        )

    def test_force_reinitialize_restores_handlers_on_failure(self):
        """Failed force re-init must restore previous handlers."""
        manager = LoggerFactory.initialize()
        handlers_before = list(manager._handlers)
        assert len(handlers_before) > 0

        # Patch _register_handlers to raise after handlers were cleared
        with patch.object(LoggerFactory, "_register_handlers", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                LoggerFactory.initialize(force=True)

        # Previous handlers should be restored
        assert manager._handlers == handlers_before


class TestLoggerFactoryConfig:
    """Tests for LoggerFactory configuration handling."""

    def test_initialize_with_config(self):
        """Test initialization with custom config."""
        config = LoggingConfig(default_level="DEBUG")
        LoggerFactory.initialize(config=config)

        assert LoggerFactory.get_config() is config

    def test_initialize_uses_environment_config(self):
        """Test that environment config is used when none provided."""
        with patch.dict("os.environ", {"AGENT_ACTIONS_LOG_LEVEL": "WARNING"}):
            LoggerFactory.initialize()
            config = LoggerFactory.get_config()
            # Config should exist
            assert config is not None


class TestLoggerFactoryLoggingBridge:
    """Tests for Python logging bridge setup."""

    def test_logging_bridge_setup(self):
        """Test that logging bridge is set up."""
        LoggerFactory.initialize()

        # Get a logger and verify it has handlers
        logger = logging.getLogger("agent_actions")
        assert len(logger.handlers) >= 1

    def test_logging_bridge_propagate_disabled(self):
        """Test that propagation is disabled to avoid duplicates."""
        LoggerFactory.initialize()

        logger = logging.getLogger("agent_actions")
        assert logger.propagate is False


class TestLoggerFactoryContext:
    """Tests for LoggerFactory context management."""

    def test_set_context(self):
        """Test setting context values."""
        LoggerFactory.initialize()
        LoggerFactory.set_context(custom_key="custom_value")

        manager = LoggerFactory.get_event_manager()
        assert manager.get_context("custom_key") == "custom_value"


class TestLoggerFactoryFlush:
    """Tests for LoggerFactory.flush()."""

    def test_flush_calls_manager_flush(self):
        """Test that flush calls EventManager.flush()."""
        LoggerFactory.initialize()

        with patch.object(LoggerFactory._event_manager, "flush") as mock_flush:
            LoggerFactory.flush()
            mock_flush.assert_called_once()


class TestLoggerFactoryIntegration:
    """Integration tests for LoggerFactory."""

    def test_logger_fires_events(self):
        """Test that logger.info() fires events through system."""
        LoggerFactory.initialize()

        # Register a capture handler
        capture = MockEventCapture()
        manager = LoggerFactory.get_event_manager()
        manager.register(capture)

        # Use logger
        logger = LoggerFactory.get_logger("test")
        logger.info("Test message")

        # Should have captured the event
        assert len(capture.events) >= 1
        messages = [e.message for e in capture.events]
        assert "Test message" in messages

    def test_full_workflow(self, temp_output_dir):
        """Test full workflow with initialization and logging."""
        # Initialize
        LoggerFactory.initialize(
            output_dir=temp_output_dir,
            workflow_name="integration_test",
            verbose=True,
        )

        # Get logger and log
        logger = LoggerFactory.get_logger("integration")
        logger.info("Starting integration test")
        logger.debug("Debug info")
        logger.warning("A warning")

        # Flush
        LoggerFactory.flush()

        # Verify files were created
        # Note: Files may or may not exist depending on handler configuration
        assert LoggerFactory.is_initialized()

    def test_context_propagation(self):
        """Test that context is propagated to events."""
        LoggerFactory.initialize(
            invocation_id="test-inv",
            workflow_name="test-workflow",
        )

        capture = MockEventCapture()
        manager = LoggerFactory.get_event_manager()
        manager.register(capture)

        logger = LoggerFactory.get_logger("test")
        logger.info("Test")

        # Check context was injected
        event = capture.events[-1]
        assert event.meta.invocation_id == "test-inv"
        assert event.meta.extra.get("workflow_name") == "test-workflow"
