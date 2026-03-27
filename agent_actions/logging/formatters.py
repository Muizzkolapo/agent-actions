"""Custom logging formatters for structured and human-readable output."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for log aggregation."""

    EXCLUDED_FIELDS: set[str] = {
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

    CONTEXT_FIELDS: set[str] = {
        "correlation_id",
        "workflow_name",
        "action_name",
        "action_index",
        "batch_id",
        "item_id",
    }

    def __init__(
        self,
        include_source_location: bool = True,
        include_process_info: bool = False,
    ) -> None:
        """Initialize the JSON formatter."""
        super().__init__()
        self.include_source_location = include_source_location
        self.include_process_info = include_process_info

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as a single-line JSON string."""
        log_dict: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in self.CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None and value != "" and value != -1:
                log_dict[field] = value

        if self.include_source_location:
            log_dict["source_file"] = record.pathname
            log_dict["source_line"] = record.lineno
            log_dict["source_function"] = record.funcName

        if self.include_process_info:
            log_dict["process"] = record.process
            log_dict["process_name"] = record.processName
            log_dict["thread"] = record.thread
            log_dict["thread_name"] = record.threadName

        if record.exc_info:
            log_dict["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            log_dict["stack_info"] = record.stack_info

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
