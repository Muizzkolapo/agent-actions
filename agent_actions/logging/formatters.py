"""Custom logging formatters for structured and human-readable output."""

from __future__ import annotations

import json
import logging
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
