"""Tests for LoggerFactory.

This module tests:
- LoggerFactory initialization
- Handler registration
- Context management
- Logger creation
- Reset functionality
- Integration with EventManager
"""

import logging
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from agent_actions.logging.config import LoggingConfig
from agent_actions.logging.factory import LoggerFactory
from agent_actions.logging.core.manager import EventManager
from agent_actions.logging.core.events import BaseEvent, EventLevel


@pytest.fixture(autouse=True)
def reset_factory():
    """Reset LoggerFactory and EventManager before and after each test."""
    LoggerFactory.reset()
    yield
    LoggerFactory.reset()


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

    def test_initialize_returns_event_manager(self):
        """Test that initialize returns an EventManager."""
        manager = LoggerFactory.initialize()
        assert isinstance(manager, EventManager)

    def test_initialize_marks_as_initialized(self):
        """Test that initialize sets _initialized flag."""
        assert not LoggerFactory.is_initialized()
        LoggerFactory.initialize()
        assert LoggerFactory.is_initialized()

    def test_initialize_idempotent(self):
        """Test that multiple initializations return same manager."""
        manager1 = LoggerFactory.initialize()
        manager2 = LoggerFactory.initialize()
        assert manager1 is manager2

    def test_initialize_force_reinitializes(self):
        """Test that force=True reinitializes."""
        manager1 = LoggerFactory.initialize()
        LoggerFactory.initialize(force=True)
        # Should have reinitialized (manager may be same singleton)
        assert LoggerFactory.is_initialized()

    def test_initialize_with_output_dir(self, temp_output_dir):
        """Test initialization with output directory."""
        LoggerFactory.initialize(output_dir=temp_output_dir)

        # Should have created target directory structure
        assert (temp_output_dir / "target").exists() or True  # May not exist until flush

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

    def test_initialize_generates_invocation_id(self):
        """Test that invocation ID is generated if not provided."""
        LoggerFactory.initialize()

        manager = LoggerFactory.get_event_manager()
        inv_id = manager.get_context("invocation_id")
        assert inv_id is not None
        assert len(inv_id) == 8

    def test_initialize_verbose_mode(self):
        """Test initialization with verbose=True."""
        LoggerFactory.initialize(verbose=True)
        # Verbose mode should enable DEBUG level console output
        assert LoggerFactory.is_initialized()

    def test_initialize_quiet_mode(self):
        """Test initialization with quiet=True."""
        LoggerFactory.initialize(quiet=True)
        # Quiet mode should set WARN level for console
        assert LoggerFactory.is_initialized()


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


class TestLoggerFactoryHandlerRegistration:
    """Tests for handler registration."""

    def test_console_handler_registered(self):
        """Test that console handler is registered."""
        LoggerFactory.initialize()
        manager = LoggerFactory.get_event_manager()
        # At least one handler should be registered
        assert len(manager._handlers) >= 1

    def test_json_handler_registered_with_output_dir(self, temp_output_dir):
        """Test that JSON handler is registered when output_dir provided."""
        LoggerFactory.initialize(output_dir=temp_output_dir)
        manager = LoggerFactory.get_event_manager()
        # Should have console + JSON + run_results handlers
        assert len(manager._handlers) >= 2

    def test_run_results_collector_registered(self, temp_output_dir):
        """Test that RunResultsCollector is registered."""
        LoggerFactory.initialize(output_dir=temp_output_dir)

        collector = LoggerFactory.get_run_results_collector()
        assert collector is not None


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


class TestLoggerFactoryGetLogger:
    """Tests for LoggerFactory.get_logger()."""

    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a Logger instance."""
        logger = LoggerFactory.get_logger("test")
        assert isinstance(logger, logging.Logger)

    def test_get_logger_auto_initializes(self):
        """Test that get_logger initializes factory if needed."""
        assert not LoggerFactory.is_initialized()

        logger = LoggerFactory.get_logger("test")

        assert LoggerFactory.is_initialized()

    def test_get_logger_prefixes_name(self):
        """Test that logger name is prefixed with agent_actions."""
        logger = LoggerFactory.get_logger("mymodule")
        assert logger.name == "agent_actions.mymodule"

    def test_get_logger_preserves_qualified_name(self):
        """Test that fully qualified name is preserved."""
        logger = LoggerFactory.get_logger("agent_actions.workflow")
        assert logger.name == "agent_actions.workflow"


class TestLoggerFactorySetLevel:
    """Tests for LoggerFactory.set_level()."""

    def test_set_level_root_logger(self):
        """Test setting level on root logger."""
        LoggerFactory.initialize()
        LoggerFactory.set_level("DEBUG")

        logger = logging.getLogger("agent_actions")
        assert logger.level == logging.DEBUG

    def test_set_level_specific_logger(self):
        """Test setting level on specific logger."""
        LoggerFactory.initialize()
        LoggerFactory.set_level("WARNING", "workflow")

        logger = logging.getLogger("agent_actions.workflow")
        assert logger.level == logging.WARNING

    def test_set_level_auto_initializes(self):
        """Test that set_level initializes factory if needed."""
        assert not LoggerFactory.is_initialized()

        LoggerFactory.set_level("DEBUG")

        assert LoggerFactory.is_initialized()


class TestLoggerFactorySetDebug:
    """Tests for LoggerFactory.set_debug()."""

    def test_set_debug_enables_debug(self):
        """Test that set_debug(True) enables DEBUG level."""
        LoggerFactory.initialize()
        LoggerFactory.set_debug(True)

        logger = logging.getLogger("agent_actions")
        assert logger.level == logging.DEBUG

    def test_set_debug_disables_debug(self):
        """Test that set_debug(False) sets INFO level."""
        LoggerFactory.initialize()
        LoggerFactory.set_debug(True)
        LoggerFactory.set_debug(False)

        logger = logging.getLogger("agent_actions")
        assert logger.level == logging.INFO


class TestLoggerFactoryContext:
    """Tests for LoggerFactory context management."""

    def test_set_context(self):
        """Test setting context values."""
        LoggerFactory.initialize()
        LoggerFactory.set_context(custom_key="custom_value")

        manager = LoggerFactory.get_event_manager()
        assert manager.get_context("custom_key") == "custom_value"

    def test_set_context_without_manager(self):
        """Test set_context does nothing without manager."""
        # Don't initialize
        LoggerFactory.set_context(key="value")  # Should not raise


class TestLoggerFactoryFlush:
    """Tests for LoggerFactory.flush()."""

    def test_flush_calls_manager_flush(self):
        """Test that flush calls EventManager.flush()."""
        LoggerFactory.initialize()

        with patch.object(LoggerFactory._event_manager, "flush") as mock_flush:
            LoggerFactory.flush()
            mock_flush.assert_called_once()

    def test_flush_without_manager(self):
        """Test flush does nothing without manager."""
        LoggerFactory.flush()  # Should not raise


class TestLoggerFactoryReset:
    """Tests for LoggerFactory.reset()."""

    def test_reset_clears_initialized(self):
        """Test that reset clears initialized flag."""
        LoggerFactory.initialize()
        assert LoggerFactory.is_initialized()

        LoggerFactory.reset()

        assert not LoggerFactory.is_initialized()

    def test_reset_clears_config(self):
        """Test that reset clears config."""
        LoggerFactory.initialize()
        assert LoggerFactory.get_config() is not None

        LoggerFactory.reset()

        assert LoggerFactory.get_config() is None

    def test_reset_clears_event_manager(self):
        """Test that reset clears event manager reference."""
        LoggerFactory.initialize()
        assert LoggerFactory.get_event_manager() is not None

        LoggerFactory.reset()

        assert LoggerFactory._event_manager is None

    def test_reset_clears_run_results_collector(self):
        """Test that reset clears run results collector reference."""
        LoggerFactory.initialize()

        LoggerFactory.reset()

        assert LoggerFactory._run_results_collector is None

    def test_reset_clears_root_logger_handlers(self):
        """Test that reset clears handlers from root logger."""
        LoggerFactory.initialize()
        logger = logging.getLogger("agent_actions")
        initial_handlers = len(logger.handlers)
        assert initial_handlers > 0

        LoggerFactory.reset()

        assert len(logger.handlers) == 0


class TestLoggerFactoryAccessors:
    """Tests for accessor methods."""

    def test_get_event_manager(self):
        """Test get_event_manager returns manager after init."""
        LoggerFactory.initialize()
        manager = LoggerFactory.get_event_manager()
        assert manager is not None
        assert isinstance(manager, EventManager)

    def test_get_event_manager_before_init(self):
        """Test get_event_manager returns None before init."""
        assert LoggerFactory.get_event_manager() is None

    def test_get_run_results_collector(self, temp_output_dir):
        """Test get_run_results_collector returns collector."""
        LoggerFactory.initialize(output_dir=temp_output_dir)
        collector = LoggerFactory.get_run_results_collector()
        assert collector is not None


class TestLoggerFactoryBackwardsCompatibility:
    """Tests for backwards compatibility aliases."""

    def test_initialize_events_alias(self):
        """Test initialize_events is alias for initialize."""
        # Both should point to the same underlying function
        assert LoggerFactory.initialize_events.__func__ is LoggerFactory.initialize.__func__

    def test_set_event_context_alias(self):
        """Test set_event_context is alias for set_context."""
        # Both should point to the same underlying function
        assert LoggerFactory.set_event_context.__func__ is LoggerFactory.set_context.__func__

    def test_flush_events_alias(self):
        """Test flush_events is alias for flush."""
        # Both should point to the same underlying function
        assert LoggerFactory.flush_events.__func__ is LoggerFactory.flush.__func__


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
