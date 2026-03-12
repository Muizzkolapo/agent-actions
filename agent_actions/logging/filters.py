"""Custom logging filters for context injection."""

from __future__ import annotations

import logging
import re
from typing import Any, List, Pattern


def _redact_sensitive_data(
    data: Any,
    redact_keys: tuple[str, ...] = (
        "api_key",
        "key",
        "token",
        "password",
        "secret",
        "authorization",
    ),
) -> Any:
    """Redact sensitive data from nested structures for logging."""
    if isinstance(data, dict):
        return {
            k: (
                "[REDACTED]"
                if any(key in k.lower() for key in redact_keys)
                else _redact_sensitive_data(v, redact_keys)
            )
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact_sensitive_data(item, redact_keys) for item in data]
    if isinstance(data, str):
        patterns = [
            (r"sk-[a-zA-Z0-9]{20,}", "sk-[REDACTED]"),
            (r"anthropic-[a-zA-Z0-9-]{20,}", "anthropic-[REDACTED]"),
            (r"AIza[a-zA-Z0-9_-]{35}", "AIza[REDACTED]"),
        ]
        result = data
        for pattern, replacement in patterns:
            result = re.sub(pattern, replacement, result)
        return result
    return data


class RedactingFilter(logging.Filter):
    """Redacts sensitive information (API keys, tokens, etc.) from log records."""

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
        """Initialize the redacting filter."""
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
        return f"{self.__class__.__name__}(patterns={len(self._compiled_patterns)})"

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive patterns from message and extra fields; always returns True."""
        msg = record.getMessage()

        for pattern, replacement in self._compiled_patterns:
            msg = pattern.sub(replacement, msg)

        record.msg = msg
        record.args = ()

        self._redact_extra_fields(record)

        return True

    def _redact_extra_fields(self, record: logging.LogRecord) -> None:
        """Redact sensitive data from extra fields in the log record."""
        sensitive_keys = ["api_key", "key", "token", "password", "secret", "authorization"]

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

        for attr in record.__dict__.keys():
            if attr in standard_attrs:
                continue

            value = getattr(record, attr, None)

            if any(key in attr.lower() for key in sensitive_keys):
                setattr(record, attr, "[REDACTED]")
            elif isinstance(value, (dict, list)):
                setattr(record, attr, self._redact_nested(value))
            elif isinstance(value, str):
                redacted_value = value
                for pattern, replacement in self._compiled_patterns:
                    redacted_value = pattern.sub(replacement, redacted_value)
                if redacted_value != value:
                    setattr(record, attr, redacted_value)

    def _redact_nested(self, data):
        """Redact sensitive data from nested structures."""
        return _redact_sensitive_data(data)
