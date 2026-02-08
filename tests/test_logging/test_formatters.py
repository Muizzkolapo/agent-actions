"""Tests for logging formatters."""

import json
import logging

from agent_actions.logging.formatters import JSONFormatter


def create_log_record(
    msg: str = "Test message",
    level: int = logging.INFO,
    exc_info=None,
    **extras,
) -> logging.LogRecord:
    """Helper to create log records for testing."""
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname="/path/to/test.py",
        lineno=42,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for key, value in extras.items():
        setattr(record, key, value)
    return record


class TestJSONFormatter:
    """Tests for JSONFormatter."""

    def test_includes_correlation_context(self):
        """Test that correlation context fields are included."""
        formatter = JSONFormatter()
        record = create_log_record(
            correlation_id="abc123",
            workflow_name="test-workflow",
            agent_name="test-agent",
            agent_index=2,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["correlation_id"] == "abc123"
        assert data["workflow_name"] == "test-workflow"
        assert data["agent_name"] == "test-agent"
        assert data["agent_index"] == 2

    def test_includes_extra_fields(self):
        """Test that extra fields are included."""
        formatter = JSONFormatter()
        record = create_log_record(
            custom_field="custom_value",
            duration_ms=123.45,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["custom_field"] == "custom_value"
        assert data["duration_ms"] == 123.45

    def test_handles_exception_info(self):
        """Test that exception info is formatted."""
        formatter = JSONFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = create_log_record(exc_info=exc_info)

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert "ValueError" in data["exception"]
        assert "Test error" in data["exception"]

    def test_handles_non_serializable_values(self):
        """Test that non-JSON-serializable values are converted to strings."""
        formatter = JSONFormatter()

        class NonSerializable:
            def __str__(self):
                return "NonSerializable object"

        record = create_log_record(custom_object=NonSerializable())

        output = formatter.format(record)
        data = json.loads(output)

        assert data["custom_object"] == "NonSerializable object"
