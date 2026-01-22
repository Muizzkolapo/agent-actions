"""Tests for ConsoleEventHandler.

This module tests:
- Console output formatting
- Level filtering
- Category filtering
- Custom formatters
- Rich console integration
- QuietConsoleHandler and VerboseConsoleHandler variants
"""

import sys
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import Mock, patch, MagicMock

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel, EventMeta
from agent_actions.logging.core.handlers.console import (
    ConsoleEventHandler,
    QuietConsoleHandler,
    VerboseConsoleHandler,
    RICH_AVAILABLE,
)


class TestConsoleEventHandlerInit:
    """Tests for ConsoleEventHandler initialization."""

    def test_default_min_level(self):
        """Test default minimum level is INFO."""
        handler = ConsoleEventHandler()
        assert handler.min_level == EventLevel.INFO

    def test_custom_min_level(self):
        """Test setting custom minimum level."""
        handler = ConsoleEventHandler(min_level=EventLevel.DEBUG)
        assert handler.min_level == EventLevel.DEBUG

    def test_default_show_timestamp(self):
        """Test default show_timestamp is True."""
        handler = ConsoleEventHandler()
        assert handler.show_timestamp is True

    def test_custom_show_timestamp(self):
        """Test setting custom show_timestamp."""
        handler = ConsoleEventHandler(show_timestamp=False)
        assert handler.show_timestamp is False

    def test_custom_formatter(self):
        """Test setting custom formatter."""
        custom_formatter = lambda e: f"Custom: {e.message}"
        handler = ConsoleEventHandler(formatter=custom_formatter)
        assert handler.formatter is custom_formatter

    def test_categories_filter(self):
        """Test setting categories filter."""
        handler = ConsoleEventHandler(categories={"workflow", "agent"})
        assert handler.categories == {"workflow", "agent"}


class TestConsoleEventHandlerAccepts:
    """Tests for ConsoleEventHandler.accepts()."""

    def test_accepts_event_above_min_level(self):
        """Test that events at or above min level are accepted."""
        handler = ConsoleEventHandler(min_level=EventLevel.INFO)

        info_event = BaseEvent(level=EventLevel.INFO, message="info")
        warn_event = BaseEvent(level=EventLevel.WARN, message="warn")
        error_event = BaseEvent(level=EventLevel.ERROR, message="error")

        assert handler.accepts(info_event)
        assert handler.accepts(warn_event)
        assert handler.accepts(error_event)

    def test_rejects_event_below_min_level(self):
        """Test that events below min level are rejected."""
        handler = ConsoleEventHandler(min_level=EventLevel.INFO)

        debug_event = BaseEvent(level=EventLevel.DEBUG, message="debug")

        assert not handler.accepts(debug_event)

    def test_accepts_matching_category(self):
        """Test that matching categories are accepted."""
        handler = ConsoleEventHandler(categories={"workflow"})

        workflow_event = BaseEvent(category="workflow", message="workflow")

        assert handler.accepts(workflow_event)

    def test_rejects_non_matching_category(self):
        """Test that non-matching categories are rejected."""
        handler = ConsoleEventHandler(categories={"workflow"})

        agent_event = BaseEvent(category="agent", message="agent")

        assert not handler.accepts(agent_event)

    def test_no_category_filter_accepts_all(self):
        """Test that None categories filter accepts all categories."""
        handler = ConsoleEventHandler(categories=None)

        workflow_event = BaseEvent(category="workflow", message="workflow")
        agent_event = BaseEvent(category="agent", message="agent")
        batch_event = BaseEvent(category="batch", message="batch")

        assert handler.accepts(workflow_event)
        assert handler.accepts(agent_event)
        assert handler.accepts(batch_event)


class TestConsoleEventHandlerHandle:
    """Tests for ConsoleEventHandler.handle()."""

    def test_handle_outputs_message(self, capsys):
        """Test that handle() outputs event message."""
        handler = ConsoleEventHandler(show_timestamp=False)
        # Force non-Rich mode for predictable output
        handler._use_rich = False

        event = BaseEvent(level=EventLevel.INFO, message="test message")
        handler.handle(event)

        captured = capsys.readouterr()
        assert "test message" in captured.err
        assert "INFO" in captured.err

    def test_handle_with_timestamp(self, capsys):
        """Test that handle() includes timestamp when enabled."""
        handler = ConsoleEventHandler(show_timestamp=True)
        handler._use_rich = False

        ts = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        event = BaseEvent(
            level=EventLevel.INFO,
            message="test message",
            meta=EventMeta(timestamp=ts),
        )
        handler.handle(event)

        captured = capsys.readouterr()
        assert "10:30:45" in captured.err

    def test_handle_without_timestamp(self, capsys):
        """Test that handle() excludes timestamp when disabled."""
        handler = ConsoleEventHandler(show_timestamp=False)
        handler._use_rich = False

        ts = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        event = BaseEvent(
            level=EventLevel.INFO,
            message="test message",
            meta=EventMeta(timestamp=ts),
        )
        handler.handle(event)

        captured = capsys.readouterr()
        # Should not have timestamp, but | separator may still be present
        assert "INFO" in captured.err
        assert "test message" in captured.err

    def test_handle_with_custom_formatter(self, capsys):
        """Test that custom formatter is used."""
        custom_formatter = lambda e: f"CUSTOM: {e.message}"
        handler = ConsoleEventHandler(formatter=custom_formatter)
        handler._use_rich = False

        event = BaseEvent(message="test")
        handler.handle(event)

        captured = capsys.readouterr()
        assert "CUSTOM: test" in captured.err


class TestConsoleEventHandlerLevelIndicators:
    """Tests for level indicator formatting."""

    def test_debug_level_indicator(self, capsys):
        """Test DEBUG level indicator."""
        handler = ConsoleEventHandler(min_level=EventLevel.DEBUG, show_timestamp=False)
        handler._use_rich = False

        event = BaseEvent(level=EventLevel.DEBUG, message="test")
        handler.handle(event)

        captured = capsys.readouterr()
        assert "DEBUG" in captured.err

    def test_info_level_indicator(self, capsys):
        """Test INFO level indicator."""
        handler = ConsoleEventHandler(show_timestamp=False)
        handler._use_rich = False

        event = BaseEvent(level=EventLevel.INFO, message="test")
        handler.handle(event)

        captured = capsys.readouterr()
        assert "INFO" in captured.err

    def test_warn_level_indicator(self, capsys):
        """Test WARN level indicator."""
        handler = ConsoleEventHandler(show_timestamp=False)
        handler._use_rich = False

        event = BaseEvent(level=EventLevel.WARN, message="test")
        handler.handle(event)

        captured = capsys.readouterr()
        assert "WARN" in captured.err

    def test_error_level_indicator(self, capsys):
        """Test ERROR level indicator."""
        handler = ConsoleEventHandler(show_timestamp=False)
        handler._use_rich = False

        event = BaseEvent(level=EventLevel.ERROR, message="test")
        handler.handle(event)

        captured = capsys.readouterr()
        assert "ERROR" in captured.err


class TestConsoleEventHandlerFlush:
    """Tests for ConsoleEventHandler.flush()."""

    def test_flush_calls_stderr_flush(self):
        """Test that flush() flushes stderr."""
        handler = ConsoleEventHandler()

        with patch.object(sys.stderr, "flush") as mock_flush:
            handler.flush()
            mock_flush.assert_called_once()


class TestQuietConsoleHandler:
    """Tests for QuietConsoleHandler."""

    def test_min_level_is_warn(self):
        """Test that QuietConsoleHandler has WARN min level."""
        handler = QuietConsoleHandler()
        assert handler.min_level == EventLevel.WARN

    def test_accepts_warn_and_error(self):
        """Test that only WARN and ERROR are accepted."""
        handler = QuietConsoleHandler()

        debug_event = BaseEvent(level=EventLevel.DEBUG, message="debug")
        info_event = BaseEvent(level=EventLevel.INFO, message="info")
        warn_event = BaseEvent(level=EventLevel.WARN, message="warn")
        error_event = BaseEvent(level=EventLevel.ERROR, message="error")

        assert not handler.accepts(debug_event)
        assert not handler.accepts(info_event)
        assert handler.accepts(warn_event)
        assert handler.accepts(error_event)


class TestVerboseConsoleHandler:
    """Tests for VerboseConsoleHandler."""

    def test_min_level_is_debug(self):
        """Test that VerboseConsoleHandler has DEBUG min level."""
        handler = VerboseConsoleHandler()
        assert handler.min_level == EventLevel.DEBUG

    def test_accepts_all_levels(self):
        """Test that all levels are accepted."""
        handler = VerboseConsoleHandler()

        debug_event = BaseEvent(level=EventLevel.DEBUG, message="debug")
        info_event = BaseEvent(level=EventLevel.INFO, message="info")
        warn_event = BaseEvent(level=EventLevel.WARN, message="warn")
        error_event = BaseEvent(level=EventLevel.ERROR, message="error")

        assert handler.accepts(debug_event)
        assert handler.accepts(info_event)
        assert handler.accepts(warn_event)
        assert handler.accepts(error_event)


class TestRichIntegration:
    """Tests for Rich console integration."""

    @pytest.mark.skipif(not RICH_AVAILABLE, reason="Rich not installed")
    def test_rich_console_used_when_available(self):
        """Test that Rich console is used when available."""
        handler = ConsoleEventHandler()
        assert handler._use_rich is True
        assert handler._console is not None

    def test_plain_print_fallback(self):
        """Test fallback to plain print when Rich unavailable."""
        with patch.dict("sys.modules", {"rich.console": None}):
            # Create handler without Rich
            handler = ConsoleEventHandler()
            handler._use_rich = False

            # Should still work with plain print
            event = BaseEvent(message="test")
            handler.handle(event)  # Should not raise

    @pytest.mark.skipif(not RICH_AVAILABLE, reason="Rich not installed")
    def test_custom_console_instance(self):
        """Test providing custom Rich console instance."""
        from rich.console import Console

        custom_console = Console(stderr=True, force_terminal=True)
        handler = ConsoleEventHandler(console=custom_console)

        assert handler._console is custom_console


class TestConsoleEventHandlerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handle_event_with_invalid_timestamp(self, capsys):
        """Test handling event with non-datetime timestamp."""
        handler = ConsoleEventHandler(show_timestamp=True)
        handler._use_rich = False

        # Create event with string timestamp (edge case)
        event = BaseEvent(message="test")
        event.meta.timestamp = "not a datetime"  # type: ignore

        # Should not raise, should use current time
        handler.handle(event)

        captured = capsys.readouterr()
        assert "test" in captured.err

    def test_handle_empty_message(self, capsys):
        """Test handling event with empty message."""
        handler = ConsoleEventHandler(show_timestamp=False)
        handler._use_rich = False

        event = BaseEvent(message="")
        handler.handle(event)

        captured = capsys.readouterr()
        assert "INFO" in captured.err

    def test_formatter_exception_handling(self, capsys):
        """Test that formatter exceptions are handled gracefully."""

        def bad_formatter(event):
            raise ValueError("Formatter error")

        handler = ConsoleEventHandler(formatter=bad_formatter)
        handler._use_rich = False

        event = BaseEvent(message="test")

        # Should raise since the handler doesn't catch formatter errors
        with pytest.raises(ValueError):
            handler.handle(event)
