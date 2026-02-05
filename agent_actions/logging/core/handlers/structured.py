"""
Structured log handler for log aggregation systems.

Outputs events in a format compatible with log aggregation systems like
ELK Stack (Elasticsearch, Logstash, Kibana), Datadog, Splunk, etc.

Uses Python's standard logging module as the backend, allowing integration
with existing logging infrastructure.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent, EventLevel


class StructuredLogHandler:
    """
    Handler that emits events to Python's logging system in structured format.

    This bridges the event system with standard Python logging, allowing
    events to flow to any configured log handlers (file, syslog, etc.).

    The output format is designed for log aggregation systems:
    - JSON-serializable
    - Consistent field names
    - ISO8601 timestamps
    - Correlation IDs for tracing

    Attributes:
        logger: Python logger instance to use
        include_stack_info: Whether to include stack traces for errors
    """

    def __init__(
        self,
        logger_name: str = "agent_actions.events",
        min_level: EventLevel | None = None,
        include_stack_info: bool = True,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the structured log handler.

        Args:
            logger_name: Name of the Python logger to use
            min_level: Minimum event level to log
            include_stack_info: Include stack traces for error events
            extra_fields: Additional fields to include in every log entry
        """
        from agent_actions.logging.core.events import EventLevel

        self.logger = logging.getLogger(logger_name)
        self.min_level = min_level or EventLevel.DEBUG
        self.include_stack_info = include_stack_info
        self.extra_fields = extra_fields or {}

    def accepts(self, event: BaseEvent) -> bool:
        """
        Check if this event should be logged.

        Args:
            event: Event to check

        Returns:
            True if event should be logged
        """
        from agent_actions.logging.core.events import EventLevel

        level_order = EventLevel.ordered()
        return level_order.index(event.level) >= level_order.index(self.min_level)

    def handle(self, event: BaseEvent) -> None:
        """
        Emit the event to Python logging.

        Args:
            event: Event to log
        """
        # Build structured log record
        log_data = self._build_log_data(event)

        # Get Python log level
        log_level = event.level.log_level

        # Emit to logger
        # We use the extra dict to pass structured data
        self.logger.log(
            log_level,
            event.message,
            extra={"structured_data": log_data},
            exc_info=self.include_stack_info and event.level.value == "error",
        )

    def flush(self) -> None:
        """Flush all logging handlers."""
        for handler in self.logger.handlers:
            handler.flush()

    def _build_log_data(self, event: BaseEvent) -> dict[str, Any]:
        """
        Build the structured log data dictionary.

        Args:
            event: Event to convert

        Returns:
            Dictionary with structured log fields
        """
        # Base fields
        data: dict[str, Any] = {
            # Standard fields for log aggregation
            "@timestamp": event.meta.timestamp.isoformat()
            if isinstance(event.meta.timestamp, datetime)
            else str(event.meta.timestamp),
            "level": event.level.value.upper(),
            "message": event.message,
            # Event identification
            "event": {
                "type": event.event_type,
                "code": event.code,
                "category": event.category,
            },
            # Tracing fields
            "trace": {
                "invocation_id": event.meta.invocation_id,
                "correlation_id": event.meta.correlation_id,
            },
        }

        # Add event-specific data
        if event.data:
            data["event"]["data"] = event.data

        # Add extra metadata
        if event.meta.extra:
            data["meta"] = event.meta.extra

        # Add handler-level extra fields
        if self.extra_fields:
            data.update(self.extra_fields)

        return data


class StructuredFormatter(logging.Formatter):
    """
    Logging formatter that outputs JSON for structured logging.

    Use this formatter with Python's logging handlers to get JSON output
    compatible with log aggregation systems.

    Example:
        handler = logging.FileHandler("app.log")
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
    """

    def __init__(
        self,
        include_timestamp: bool = True,
        include_logger: bool = True,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the formatter.

        Args:
            include_timestamp: Include @timestamp field
            include_logger: Include logger name field
            extra_fields: Additional fields for every log entry
        """
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_logger = include_logger
        self.extra_fields = extra_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record as JSON.

        Args:
            record: Python LogRecord to format

        Returns:
            JSON string
        """
        # Check if we have structured event data
        structured_data = getattr(record, "structured_data", None)

        if structured_data:
            # Event system data - use as-is with some additions
            data = structured_data.copy()
        else:
            # Regular log message - wrap in structure
            data = {
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
            }

        # Add standard fields
        if self.include_timestamp and "@timestamp" not in data:
            data["@timestamp"] = datetime.utcnow().isoformat() + "Z"

        if self.include_logger:
            data["logger"] = record.name

        # Add exception info if present
        if record.exc_info:
            data["error"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "stack_trace": self.formatException(record.exc_info),
            }

        # Add extra fields
        data.update(self.extra_fields)

        return json.dumps(data, default=str)
