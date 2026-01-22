"""
Logging bridge that converts Python logging to events.

This handler bridges the gap between Python's standard logging and the
event system, allowing existing logger.info(), logger.debug() calls to
automatically become events.

This enables gradual migration - all existing logging code continues to
work but output flows through the centralized event system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


class LoggingBridgeHandler(logging.Handler):
    """
    Python logging handler that converts log records to events.

    When attached to Python's logging system, this handler intercepts
    all log records and fires them as events through the EventManager.

    Usage:
        # Automatic setup via LoggerFactory
        LoggerFactory.initialize()  # Sets up the bridge

        # Then all logging calls become events
        logger = logging.getLogger('my_module')
        logger.info("Hello")  # → fires LogEvent through EventManager

    This allows:
    - Existing code using logger.* to work unchanged
    - All output to flow through the event system
    - Consistent formatting and routing via event handlers
    """

    def __init__(self, level: int = logging.DEBUG) -> None:
        """
        Initialize the bridge handler.

        Args:
            level: Minimum log level to bridge (default: DEBUG - bridge everything)
        """
        super().__init__(level)
        self._event_manager = None

    def emit(self, record: logging.LogRecord) -> None:
        """
        Convert a log record to an event and fire it.

        Args:
            record: Python LogRecord to convert
        """
        try:
            # Lazy import to avoid circular dependency
            from agent_actions.logging.core.events import EventLevel
            from agent_actions.logging.core.manager import EventManager

            # Get or cache event manager
            if self._event_manager is None:
                self._event_manager = EventManager.get()

            # Map Python log level to EventLevel
            level_map = {
                logging.DEBUG: EventLevel.DEBUG,
                logging.INFO: EventLevel.INFO,
                logging.WARNING: EventLevel.WARN,
                logging.ERROR: EventLevel.ERROR,
                logging.CRITICAL: EventLevel.ERROR,
            }
            event_level = level_map.get(record.levelno, EventLevel.INFO)

            # Determine category from logger name
            # e.g., "agent_actions.workflow.coordinator" -> "workflow"
            category = self._extract_category(record.name)

            # Create a LogEvent
            event = LogEvent(
                level=event_level,
                category=category,
                message=record.getMessage(),
                logger_name=record.name,
                source_file=record.pathname,
                source_line=record.lineno,
                func_name=record.funcName,
                exc_info=record.exc_info,
            )

            # Copy extra fields if present
            if hasattr(record, "operation"):
                event.data["operation"] = record.operation
            if hasattr(record, "agent_name"):
                event.data["agent_name"] = record.agent_name
            if hasattr(record, "workflow_name"):
                event.data["workflow_name"] = record.workflow_name

            # Fire the event
            self._event_manager.fire(event)

        except Exception:
            # Don't let bridge errors break the application
            # Fall back to default handling
            self.handleError(record)

    def _extract_category(self, logger_name: str) -> str:
        """
        Extract category from logger name.

        Args:
            logger_name: Full logger name (e.g., "agent_actions.workflow.coordinator")

        Returns:
            Category string (e.g., "workflow")
        """
        parts = logger_name.split(".")
        if len(parts) >= 2 and parts[0] == "agent_actions":
            return parts[1]  # Return the module name
        return "system"


# =============================================================================
# Log Event Type
# =============================================================================

from dataclasses import dataclass
from typing import Optional, Tuple, Type
from agent_actions.logging.core.events import BaseEvent, EventLevel


@dataclass
class LogEvent(BaseEvent):
    """
    Event representing a Python log record.

    This event type wraps Python logging calls, preserving source information
    and allowing them to flow through the event system.
    """

    logger_name: str = ""
    source_file: str = ""
    source_line: int = 0
    func_name: str = ""
    exc_info: Optional[Tuple[Type[BaseException], BaseException, Any]] = None

    def __post_init__(self) -> None:
        # Category is set by bridge based on logger name
        if not self.category:
            self.category = "log"

    @property
    def code(self) -> str:
        """Log events use 'X' prefix for system/debug."""
        return f"X{abs(hash(self.logger_name)) % 1000:03d}"

    @property
    def has_exception(self) -> bool:
        """Check if this log event has exception info."""
        return self.exc_info is not None and self.exc_info[0] is not None


@dataclass
class DebugEvent(BaseEvent):
    """Event for debug-level information."""

    module: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = "debug"

    @property
    def code(self) -> str:
        return "X001"


@dataclass
class SystemEvent(BaseEvent):
    """Event for system-level information (startup, shutdown, etc.)."""

    operation: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.level:
            self.level = EventLevel.INFO
        self.category = "system"

    @property
    def code(self) -> str:
        return "X002"
