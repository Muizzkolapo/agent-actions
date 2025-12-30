"""Custom logging formatters for structured and human-readable output."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Set


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for log aggregation.

    This formatter outputs each log record as a single JSON line, making it
    suitable for log aggregation systems like ELK, Splunk, or CloudWatch.

    Example output:
        {
            "timestamp": "2024-01-15T10:30:45.123Z",
            "level": "INFO",
            "logger": "agent_actions.workflow",
            "message": "Starting workflow",
            "correlation_id": "abc123"
        }
    """

    # Fields that are handled explicitly and shouldn't be added from record.__dict__
    EXCLUDED_FIELDS: Set[str] = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }

    # Context fields that we handle explicitly
    CONTEXT_FIELDS: Set[str] = {
        "correlation_id",
        "workflow_name",
        "agent_name",
        "agent_index",
        "batch_id",
        "item_id",
    }

    def __init__(
        self,
        include_source_location: bool = True,
        include_process_info: bool = False,
    ) -> None:
        """Initialize the JSON formatter.

        Args:
            include_source_location: Whether to include file and line info.
            include_process_info: Whether to include process/thread info.
        """
        super().__init__()
        self.include_source_location = include_source_location
        self.include_process_info = include_process_info

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string.

        Args:
            record: The log record to format.

        Returns:
            Single-line JSON string representation of the record.
        """
        log_dict: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add correlation context if present
        for field in self.CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None and value != "" and value != -1:
                log_dict[field] = value

        # Add source location if enabled
        if self.include_source_location:
            log_dict["source_file"] = record.pathname
            log_dict["source_line"] = record.lineno
            log_dict["source_function"] = record.funcName

        # Add process info if enabled
        if self.include_process_info:
            log_dict["process"] = record.process
            log_dict["process_name"] = record.processName
            log_dict["thread"] = record.thread
            log_dict["thread_name"] = record.threadName

        # Add exception info if present
        if record.exc_info:
            log_dict["exception"] = self.formatException(record.exc_info)

        # Add stack info if present
        if record.stack_info:
            log_dict["stack_info"] = record.stack_info

        # Add any extra fields from the record
        for key, value in record.__dict__.items():
            if (
                key not in self.EXCLUDED_FIELDS
                and key not in self.CONTEXT_FIELDS
                and not key.startswith("_")
            ):
                try:
                    # Test if value is JSON serializable
                    json.dumps(value)
                    log_dict[key] = value
                except (TypeError, ValueError):
                    # Convert non-serializable values to string
                    log_dict[key] = str(value)

        return json.dumps(log_dict, default=str, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Formats log records for human readability with colors.

    This formatter outputs log records in a human-friendly format with
    color coding based on log level (when output supports ANSI colors).

    Example output:
        14:30:45.123 INFO     [abc123] [my-agent] Starting processing
    """

    # ANSI color codes for different log levels
    LEVEL_COLORS: Dict[str, str] = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    DIM = "\033[2m"

    def __init__(
        self,
        use_colors: bool | None = None,
        include_source_location: bool = False,
    ) -> None:
        """Initialize the human formatter.

        Args:
            use_colors: Whether to use ANSI colors. If None, auto-detect based on TTY.
            include_source_location: Whether to include file:line in output.
        """
        super().__init__()
        if use_colors is None:
            # Auto-detect: use colors if stdout is a TTY
            self.use_colors = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        else:
            self.use_colors = use_colors
        self.include_source_location = include_source_location

    def _format_level(self, level: str) -> str:
        """Format log level with optional color."""
        if self.use_colors:
            color = self.LEVEL_COLORS.get(level, "")
            return f"{color}{level:8}{self.RESET}"
        return f"{level:8}"

    def _build_context_prefix(self, record: logging.LogRecord) -> str:
        """Build context prefix from record attributes."""
        prefix_parts = []

        # Add correlation ID if present
        correlation_id = getattr(record, "correlation_id", "")
        if correlation_id:
            if self.use_colors:
                prefix_parts.append(f"{self.DIM}[{correlation_id}]{self.RESET}")
            else:
                prefix_parts.append(f"[{correlation_id}]")

        # Add agent name if present
        agent_name = getattr(record, "agent_name", "")
        if agent_name:
            if self.use_colors:
                prefix_parts.append(f"{self.DIM}[{agent_name}]{self.RESET}")
            else:
                prefix_parts.append(f"[{agent_name}]")

        prefix = " ".join(prefix_parts)
        return f"{prefix} " if prefix else ""

    def _add_source_location(self, formatted: str, record: logging.LogRecord) -> str:
        """Add source location to formatted string."""
        location = f"{record.filename}:{record.lineno}"
        if self.use_colors:
            return f"{formatted} {self.DIM}({location}){self.RESET}"
        return f"{formatted} ({location})"

    def _add_extra_info(self, formatted: str, record: logging.LogRecord) -> str:
        """Add exception and stack info to formatted string."""
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            formatted = f"{formatted}\n{exc_text}"

        if record.stack_info:
            formatted = f"{formatted}\n{record.stack_info}"

        return formatted

    def format(self, record: logging.LogRecord) -> str:
        """Format record for human readability.

        Args:
            record: The log record to format.

        Returns:
            Formatted string suitable for console output.
        """
        # Format timestamp
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Format level with color
        level_str = self._format_level(record.levelname)

        # Build context prefix
        prefix = self._build_context_prefix(record)

        # Build the main message
        message = record.getMessage()

        # Format base output
        formatted = f"{timestamp} {level_str} {prefix}{message}"

        # Add source location if enabled
        if self.include_source_location:
            formatted = self._add_source_location(formatted, record)

        # Add exception and stack info
        formatted = self._add_extra_info(formatted, record)

        return formatted


class SimpleFormatter(logging.Formatter):
    """Simple formatter without colors for file output or minimal logging.

    Example output:
        2024-01-15 14:30:45.123 INFO [abc123] Starting processing
    """

    def __init__(self, include_timestamp: bool = True) -> None:
        """Initialize the simple formatter.

        Args:
            include_timestamp: Whether to include timestamp in output.
        """
        super().__init__()
        self.include_timestamp = include_timestamp

    def format(self, record: logging.LogRecord) -> str:
        """Format record as simple string.

        Args:
            record: The log record to format.

        Returns:
            Formatted string.
        """
        parts = []

        # Add timestamp if enabled
        if self.include_timestamp:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            parts.append(timestamp)

        # Add level
        parts.append(record.levelname)

        # Add correlation ID if present
        correlation_id = getattr(record, "correlation_id", "")
        if correlation_id:
            parts.append(f"[{correlation_id}]")

        # Add agent name if present
        agent_name = getattr(record, "agent_name", "")
        if agent_name:
            parts.append(f"[{agent_name}]")

        # Add message
        parts.append(record.getMessage())

        formatted = " ".join(parts)

        # Add exception info if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            formatted = f"{formatted}\n{exc_text}"

        return formatted
