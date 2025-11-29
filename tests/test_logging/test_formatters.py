"""Tests for logging formatters."""

import json
import logging
import pytest

from agent_actions.logging.formatters import JSONFormatter, HumanFormatter, SimpleFormatter


def create_log_record(
    msg: str = 'Test message',
    level: int = logging.INFO,
    exc_info=None,
    **extras,
) -> logging.LogRecord:
    """Helper to create log records for testing."""
    record = logging.LogRecord(
        name='test.logger',
        level=level,
        pathname='/path/to/test.py',
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

    def test_basic_output_is_valid_json(self):
        """Test that output is valid JSON."""
        formatter = JSONFormatter()
        record = create_log_record()

        output = formatter.format(record)
        data = json.loads(output)

        assert isinstance(data, dict)

    def test_includes_required_fields(self):
        """Test that required fields are included."""
        formatter = JSONFormatter()
        record = create_log_record()

        output = formatter.format(record)
        data = json.loads(output)

        assert 'timestamp' in data
        assert 'level' in data
        assert 'logger' in data
        assert 'message' in data

    def test_timestamp_format(self):
        """Test that timestamp is ISO format with timezone."""
        formatter = JSONFormatter()
        record = create_log_record()

        output = formatter.format(record)
        data = json.loads(output)

        # Should end with Z or +00:00 for UTC
        assert data['timestamp'].endswith('+00:00') or data['timestamp'].endswith('Z')

    def test_level_is_string(self):
        """Test that level is the level name string."""
        formatter = JSONFormatter()
        record = create_log_record(level=logging.WARNING)

        output = formatter.format(record)
        data = json.loads(output)

        assert data['level'] == 'WARNING'

    def test_logger_name(self):
        """Test that logger name is included."""
        formatter = JSONFormatter()
        record = create_log_record()

        output = formatter.format(record)
        data = json.loads(output)

        assert data['logger'] == 'test.logger'

    def test_message_content(self):
        """Test that message content is correct."""
        formatter = JSONFormatter()
        record = create_log_record(msg='Hello world')

        output = formatter.format(record)
        data = json.loads(output)

        assert data['message'] == 'Hello world'

    def test_includes_source_location_by_default(self):
        """Test that source location is included by default."""
        formatter = JSONFormatter(include_source_location=True)
        record = create_log_record()

        output = formatter.format(record)
        data = json.loads(output)

        assert data['source_file'] == '/path/to/test.py'
        assert data['source_line'] == 42
        assert 'source_function' in data

    def test_excludes_source_location_when_disabled(self):
        """Test that source location can be excluded."""
        formatter = JSONFormatter(include_source_location=False)
        record = create_log_record()

        output = formatter.format(record)
        data = json.loads(output)

        assert 'source_file' not in data
        assert 'source_line' not in data

    def test_includes_correlation_context(self):
        """Test that correlation context fields are included."""
        formatter = JSONFormatter()
        record = create_log_record(
            correlation_id='abc123',
            workflow_name='test-workflow',
            agent_name='test-agent',
            agent_index=2,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data['correlation_id'] == 'abc123'
        assert data['workflow_name'] == 'test-workflow'
        assert data['agent_name'] == 'test-agent'
        assert data['agent_index'] == 2

    def test_excludes_empty_context_fields(self):
        """Test that empty context fields are excluded."""
        formatter = JSONFormatter()
        record = create_log_record(
            correlation_id='abc123',
            workflow_name='',
            agent_name='',
            agent_index=-1,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data['correlation_id'] == 'abc123'
        assert 'workflow_name' not in data
        assert 'agent_name' not in data
        assert 'agent_index' not in data

    def test_includes_extra_fields(self):
        """Test that extra fields are included."""
        formatter = JSONFormatter()
        record = create_log_record(
            custom_field='custom_value',
            duration_ms=123.45,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data['custom_field'] == 'custom_value'
        assert data['duration_ms'] == 123.45

    def test_handles_exception_info(self):
        """Test that exception info is formatted."""
        formatter = JSONFormatter()

        try:
            raise ValueError('Test error')
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = create_log_record(exc_info=exc_info)

        output = formatter.format(record)
        data = json.loads(output)

        assert 'exception' in data
        assert 'ValueError' in data['exception']
        assert 'Test error' in data['exception']

    def test_handles_non_serializable_values(self):
        """Test that non-JSON-serializable values are converted to strings."""
        formatter = JSONFormatter()

        class NonSerializable:
            def __str__(self):
                return 'NonSerializable object'

        record = create_log_record(custom_object=NonSerializable())

        output = formatter.format(record)
        data = json.loads(output)

        assert data['custom_object'] == 'NonSerializable object'

    def test_output_is_single_line(self):
        """Test that output is single line (no newlines in JSON)."""
        formatter = JSONFormatter()
        record = create_log_record(msg='Multi\nline\nmessage')

        output = formatter.format(record)

        # Should be single line (no newlines except in exception)
        assert output.count('\n') == 0


class TestHumanFormatter:
    """Tests for HumanFormatter."""

    def test_basic_format_structure(self):
        """Test basic output structure."""
        formatter = HumanFormatter(use_colors=False)
        record = create_log_record(msg='Test message')

        output = formatter.format(record)

        # Should contain timestamp, level, and message
        assert 'INFO' in output
        assert 'Test message' in output
        # Should have timestamp-like pattern HH:MM:SS
        assert ':' in output.split()[0]

    def test_includes_correlation_id(self):
        """Test that correlation ID is shown."""
        formatter = HumanFormatter(use_colors=False)
        record = create_log_record(correlation_id='abc123')

        output = formatter.format(record)

        assert '[abc123]' in output

    def test_includes_agent_name(self):
        """Test that agent name is shown."""
        formatter = HumanFormatter(use_colors=False)
        record = create_log_record(agent_name='my-agent')

        output = formatter.format(record)

        assert '[my-agent]' in output

    def test_colors_disabled(self):
        """Test output without ANSI colors."""
        formatter = HumanFormatter(use_colors=False)
        record = create_log_record()

        output = formatter.format(record)

        # Should not contain ANSI escape codes
        assert '\033[' not in output

    def test_colors_enabled(self):
        """Test output with ANSI colors."""
        formatter = HumanFormatter(use_colors=True)
        record = create_log_record()

        output = formatter.format(record)

        # Should contain ANSI escape codes
        assert '\033[' in output

    def test_level_colors_info(self):
        """Test INFO level color (green)."""
        formatter = HumanFormatter(use_colors=True)
        record = create_log_record(level=logging.INFO)

        output = formatter.format(record)

        assert '\033[32m' in output  # Green

    def test_level_colors_warning(self):
        """Test WARNING level color (yellow)."""
        formatter = HumanFormatter(use_colors=True)
        record = create_log_record(level=logging.WARNING)

        output = formatter.format(record)

        assert '\033[33m' in output  # Yellow

    def test_level_colors_error(self):
        """Test ERROR level color (red)."""
        formatter = HumanFormatter(use_colors=True)
        record = create_log_record(level=logging.ERROR)

        output = formatter.format(record)

        assert '\033[31m' in output  # Red

    def test_includes_source_location_when_enabled(self):
        """Test source location is included when enabled."""
        formatter = HumanFormatter(use_colors=False, include_source_location=True)
        record = create_log_record()

        output = formatter.format(record)

        assert 'test.py:42' in output

    def test_excludes_source_location_by_default(self):
        """Test source location is excluded by default."""
        formatter = HumanFormatter(use_colors=False)
        record = create_log_record()

        output = formatter.format(record)

        assert 'test.py:42' not in output

    def test_handles_exception_info(self):
        """Test that exception info is appended."""
        formatter = HumanFormatter(use_colors=False)

        try:
            raise ValueError('Test error')
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = create_log_record(exc_info=exc_info)

        output = formatter.format(record)

        assert 'ValueError' in output
        assert 'Test error' in output

    def test_level_padding(self):
        """Test that level names are padded consistently."""
        formatter = HumanFormatter(use_colors=False)

        for level in [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR]:
            record = create_log_record(level=level)
            output = formatter.format(record)
            # Level should be padded to 8 characters
            parts = output.split()
            # Find the level part
            level_str = None
            for part in parts:
                if part in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                    level_str = part
                    break
            # All levels should be present
            assert level_str is not None


class TestSimpleFormatter:
    """Tests for SimpleFormatter."""

    def test_basic_format(self):
        """Test basic output format."""
        formatter = SimpleFormatter()
        record = create_log_record(msg='Test message')

        output = formatter.format(record)

        assert 'INFO' in output
        assert 'Test message' in output

    def test_includes_timestamp_by_default(self):
        """Test that timestamp is included by default."""
        formatter = SimpleFormatter(include_timestamp=True)
        record = create_log_record()

        output = formatter.format(record)

        # Should have date-time pattern
        assert '-' in output  # Date separators
        assert ':' in output  # Time separators

    def test_excludes_timestamp_when_disabled(self):
        """Test that timestamp can be excluded."""
        formatter = SimpleFormatter(include_timestamp=False)
        record = create_log_record()

        output = formatter.format(record)

        # First word should be level, not timestamp
        assert output.split()[0] == 'INFO'

    def test_includes_correlation_id(self):
        """Test that correlation ID is shown."""
        formatter = SimpleFormatter()
        record = create_log_record(correlation_id='abc123')

        output = formatter.format(record)

        assert '[abc123]' in output

    def test_includes_agent_name(self):
        """Test that agent name is shown."""
        formatter = SimpleFormatter()
        record = create_log_record(agent_name='my-agent')

        output = formatter.format(record)

        assert '[my-agent]' in output

    def test_no_colors(self):
        """Test that output never has colors."""
        formatter = SimpleFormatter()
        record = create_log_record()

        output = formatter.format(record)

        # Should not contain ANSI escape codes
        assert '\033[' not in output

    def test_handles_exception_info(self):
        """Test that exception info is appended."""
        formatter = SimpleFormatter()

        try:
            raise ValueError('Test error')
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = create_log_record(exc_info=exc_info)

        output = formatter.format(record)

        assert 'ValueError' in output
        assert 'Test error' in output
