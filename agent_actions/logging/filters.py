"""Custom logging filters for context injection."""

from __future__ import annotations

import logging
import re
from typing import List, Pattern

from agent_actions.llm.providers.client_base import BaseClient


class RedactingFilter(logging.Filter):
    """Redacts sensitive information from log records.

    This filter applies regex patterns to redact sensitive data like
    API keys, secrets, and tokens from log messages.

    Example:
        >>> filter = RedactingFilter()
        >>> # Log message "api_key=sk-abc123" becomes "api_key=***"
    """

    DEFAULT_PATTERNS: List[str] = [
        r'api[_-]?key["\']?\s*[:=]\s*["\']?[\w-]+',
        r'secret["\']?\s*[:=]\s*["\']?[\w-]+',
        r'token["\']?\s*[:=]\s*["\']?[\w-]+',
        r'password["\']?\s*[:=]\s*["\']?[\w-]+',
        r"sk-[a-zA-Z0-9]{20,}",  # OpenAI keys
        r"sk-ant-[a-zA-Z0-9-]{20,}",  # Anthropic keys
        r"AIza[a-zA-Z0-9_-]{35}",  # Google API keys
    ]

    def __init__(
        self,
        patterns: List[str] | None = None,
        name: str = "",
    ) -> None:
        """Initialize the redacting filter.

        Args:
            patterns: List of regex patterns to redact. Uses DEFAULT_PATTERNS if None.
            name: Filter name for logging.Filter base class.
        """
        super().__init__(name)
        pattern_list = patterns if patterns is not None else self.DEFAULT_PATTERNS
        self._compiled_patterns: List[tuple[Pattern, str]] = []

        for pattern in pattern_list:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                # Determine replacement based on pattern type
                if "api" in pattern.lower():
                    replacement = "api_key=***"
                elif "secret" in pattern.lower():
                    replacement = "secret=***"
                elif "token" in pattern.lower():
                    replacement = "token=***"
                elif "password" in pattern.lower():
                    replacement = "password=***"
                elif pattern.startswith(r"sk-"):
                    replacement = "sk-***"
                elif pattern.startswith(r"sk-ant"):
                    replacement = "sk-ant-***"
                elif pattern.startswith(r"AIza"):
                    replacement = "AIza***"
                else:
                    replacement = "***"
                self._compiled_patterns.append((compiled, replacement))
            except re.error:
                # Skip invalid patterns
                pass

    def __repr__(self) -> str:
        """Return string representation of filter."""
        return f"{self.__class__.__name__}(patterns={len(self._compiled_patterns)})"

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive patterns from message and extra fields.

        Args:
            record: The log record to modify.

        Returns:
            True to allow the record to be logged.
        """
        # Get the formatted message
        msg = record.getMessage()

        # Apply redaction patterns to message
        for pattern, replacement in self._compiled_patterns:
            msg = pattern.sub(replacement, msg)

        # Update the record with redacted message
        record.msg = msg
        record.args = ()

        # Redact sensitive data in extra fields
        self._redact_extra_fields(record)

        return True

    def _redact_extra_fields(self, record: logging.LogRecord) -> None:
        """Redact sensitive data from extra fields in log record.

        Args:
            record: The log record to modify.
        """
        # Sensitive key patterns to check in attribute names
        sensitive_keys = ["api_key", "key", "token", "password", "secret", "authorization"]

        # Standard LogRecord attributes that should not be redacted
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "getMessage",
            "correlation_id",
            "workflow_name",
            "agent_name",
            "agent_index",
            "batch_id",
            "item_id",
        }

        # Iterate through record attributes (extra fields are added as attributes)
        for attr in record.__dict__.keys():
            if attr in standard_attrs:
                continue

            value = getattr(record, attr, None)

            # Check if attribute name contains sensitive keywords
            if any(key in attr.lower() for key in sensitive_keys):
                setattr(record, attr, "[REDACTED]")
            # Recursively redact nested structures (dicts, lists)
            elif isinstance(value, (dict, list)):
                setattr(record, attr, self._redact_nested(value))
            # Redact string values that match patterns
            elif isinstance(value, str):
                redacted_value = value
                for pattern, replacement in self._compiled_patterns:
                    redacted_value = pattern.sub(replacement, redacted_value)
                if redacted_value != value:
                    setattr(record, attr, redacted_value)

    def _redact_nested(self, data):
        """Redact sensitive data from nested structures.

        Uses the redaction utility from BaseClient for consistent redaction.

        Args:
            data: Nested dict or list to redact.

        Returns:
            Redacted copy of the data.
        """
        return BaseClient.redact_sensitive_data(data)
