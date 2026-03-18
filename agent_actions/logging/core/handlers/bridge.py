"""Logging bridge that converts Python logging calls to events."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


class LoggingBridgeHandler(logging.Handler):
    """Python logging handler that converts log records to events via EventManager."""

    def __init__(self, level: int = logging.DEBUG) -> None:
        """Initialize the bridge handler."""
        super().__init__(level)
        self._event_manager: Any | None = None

    def emit(self, record: logging.LogRecord) -> None:
        """Convert a log record to an event and fire it."""
        try:
            from agent_actions.logging.core.events import EventLevel
            from agent_actions.logging.core.manager import EventManager

            if self._event_manager is None:
                self._event_manager = EventManager.get()

            level_map = {
                logging.DEBUG: EventLevel.DEBUG,
                logging.INFO: EventLevel.INFO,
                logging.WARNING: EventLevel.WARN,
                logging.ERROR: EventLevel.ERROR,
                logging.CRITICAL: EventLevel.ERROR,
            }
            event_level = level_map.get(record.levelno, EventLevel.INFO)

            category = self._extract_category(record.name)

            # Normalize exc_info: filter out the (None, None, None) tuple form
            exc_info_normalized: tuple[type[BaseException], BaseException, Any] | None = None
            if record.exc_info is not None and record.exc_info[0] is not None:
                exc_info_normalized = (record.exc_info[0], record.exc_info[1], record.exc_info[2])  # type: ignore[assignment]

            event = LogEvent(
                level=event_level,
                category=category,
                message=record.getMessage(),
                logger_name=record.name,
                source_file=record.pathname,
                source_line=record.lineno,
                func_name=record.funcName,
                exc_info=exc_info_normalized,
            )

            if hasattr(record, "operation"):
                event.data["operation"] = record.operation
            if hasattr(record, "action_name"):
                event.data["action_name"] = record.action_name
            if hasattr(record, "workflow_name"):
                event.data["workflow_name"] = record.workflow_name

            self._event_manager.fire(event)

        except Exception:
            # Don't let bridge errors break the application
            # Fall back to default handling
            self.handleError(record)

    def _extract_category(self, logger_name: str) -> str:
        """Extract category from logger name (e.g. 'agent_actions.workflow.x' -> 'workflow')."""
        parts = logger_name.split(".")
        if len(parts) >= 2 and parts[0] == "agent_actions":
            return parts[1]  # Return the module name
        return "system"


# =============================================================================
# Log Event Type
# =============================================================================

from dataclasses import dataclass

from agent_actions.logging.core.events import BaseEvent, EventLevel


@dataclass
class LogEvent(BaseEvent):
    """Event representing a Python log record bridged to the event system."""

    logger_name: str = ""
    source_file: str = ""
    source_line: int = 0
    func_name: str = ""
    exc_info: tuple[type[BaseException], BaseException, Any] | None = None

    def __post_init__(self) -> None:
        if not self.category:
            self.category = "log"

    @property
    def code(self) -> str:
        """Log events use 'X' prefix for bridged log records."""
        return "X000"

    @property
    def has_exception(self) -> bool:
        """Check if this log event has exception info."""
        return self.exc_info is not None and self.exc_info[0] is not None

    def to_dict(self) -> dict[str, Any]:
        """Include diagnostic fields in serialized output."""
        d = super().to_dict()
        d["logger_name"] = self.logger_name
        d["source_file"] = self.source_file
        d["source_line"] = self.source_line
        d["func_name"] = self.func_name
        if self.has_exception and self.exc_info is not None:
            import traceback

            d["exc_info"] = "".join(traceback.format_exception(*self.exc_info))
        return d


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
        self.category = "system"

    @property
    def code(self) -> str:
        return "X002"
