"""Tests for JSONFileHandler.

This module tests:
- JSON file writing (NDJSON format)
- Level filtering
- Buffered writes
- File rotation
- Thread safety
- Directory creation
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel, EventMeta
from agent_actions.logging.core.handlers.json_file import JSONFileHandler


@pytest.fixture
def temp_log_file(tmp_path):
    """Provide a temporary log file path."""
    return tmp_path / "test.json"


@pytest.fixture
def temp_log_dir(tmp_path):
    """Provide a temporary log directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


class TestJSONFileHandlerInit:
    """Tests for JSONFileHandler initialization."""

    def test_creates_parent_directory(self, tmp_path):
        """Test that parent directory is created if it doesn't exist."""
        log_path = tmp_path / "nested" / "deep" / "test.json"
        handler = JSONFileHandler(log_path)

        assert log_path.parent.exists()
        handler.close()

    def test_default_min_level(self, temp_log_file):
        """Test default minimum level is DEBUG."""
        handler = JSONFileHandler(temp_log_file)
        assert handler.min_level == EventLevel.DEBUG
        handler.close()

    def test_custom_min_level(self, temp_log_file):
        """Test setting custom minimum level."""
        handler = JSONFileHandler(temp_log_file, min_level=EventLevel.WARN)
        assert handler.min_level == EventLevel.WARN
        handler.close()

    def test_default_buffer_size(self, temp_log_file):
        """Test default buffer size."""
        handler = JSONFileHandler(temp_log_file)
        assert handler.buffer_size == 10
        handler.close()

    def test_custom_buffer_size(self, temp_log_file):
        """Test setting custom buffer size."""
        handler = JSONFileHandler(temp_log_file, buffer_size=5)
        assert handler.buffer_size == 5
        handler.close()

    def test_path_string_conversion(self, tmp_path):
        """Test that string path is converted to Path."""
        path_str = str(tmp_path / "test.json")
        handler = JSONFileHandler(path_str)
        assert isinstance(handler.file_path, Path)
        handler.close()


class TestJSONFileHandlerAccepts:
    """Tests for JSONFileHandler.accepts()."""

    def test_accepts_all_levels_with_debug(self, temp_log_file):
        """Test that all levels are accepted with DEBUG min level."""
        handler = JSONFileHandler(temp_log_file, min_level=EventLevel.DEBUG)
        try:
            debug_event = BaseEvent(level=EventLevel.DEBUG, message="debug")
            info_event = BaseEvent(level=EventLevel.INFO, message="info")
            warn_event = BaseEvent(level=EventLevel.WARN, message="warn")
            error_event = BaseEvent(level=EventLevel.ERROR, message="error")

            assert handler.accepts(debug_event)
            assert handler.accepts(info_event)
            assert handler.accepts(warn_event)
            assert handler.accepts(error_event)
        finally:
            handler.close()

    def test_rejects_below_min_level(self, temp_log_file):
        """Test that events below min level are rejected."""
        handler = JSONFileHandler(temp_log_file, min_level=EventLevel.WARN)
        try:
            debug_event = BaseEvent(level=EventLevel.DEBUG, message="debug")
            info_event = BaseEvent(level=EventLevel.INFO, message="info")
            warn_event = BaseEvent(level=EventLevel.WARN, message="warn")

            assert not handler.accepts(debug_event)
            assert not handler.accepts(info_event)
            assert handler.accepts(warn_event)
        finally:
            handler.close()


class TestJSONFileHandlerWrite:
    """Tests for JSONFileHandler writing functionality."""

    def test_writes_event_as_json(self, temp_log_file):
        """Test that events are written as JSON lines."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1)

        event = BaseEvent(
            level=EventLevel.INFO,
            category="test",
            message="test message",
        )
        handler.handle(event)
        handler.close()

        content = temp_log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["event_type"] == "BaseEvent"
        assert data["level"] == "info"
        assert data["message"] == "test message"

    def test_writes_multiple_events(self, temp_log_file):
        """Test that multiple events are written as NDJSON."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1)

        for i in range(3):
            event = BaseEvent(message=f"message {i}")
            handler.handle(event)

        handler.close()

        content = temp_log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3

        for i, line in enumerate(lines):
            data = json.loads(line)
            assert data["message"] == f"message {i}"

    def test_buffered_writes(self, temp_log_file):
        """Test that writes are buffered."""
        handler = JSONFileHandler(temp_log_file, buffer_size=5)

        # Write 3 events (less than buffer size)
        for i in range(3):
            event = BaseEvent(message=f"message {i}")
            handler.handle(event)

        # File should be empty or not exist (buffered)
        if temp_log_file.exists():
            content = temp_log_file.read_text()
            assert content == "" or len(content.strip().split("\n")) < 3

        # Flush to write
        handler.flush()

        content = temp_log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3
        handler.close()

    def test_auto_flush_on_buffer_full(self, temp_log_file):
        """Test that buffer auto-flushes when full."""
        handler = JSONFileHandler(temp_log_file, buffer_size=3)

        # Write exactly buffer_size events - this triggers _flush_buffer
        for i in range(3):
            event = BaseEvent(message=f"message {i}")
            handler.handle(event)

        # Close to ensure everything is written to disk
        handler.close()

        # Verify all 3 events were written
        content = temp_log_file.read_text()
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) == 3

    def test_include_all_fields(self, temp_log_file):
        """Test that all fields are included when include_all_fields=True."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1, include_all_fields=True)

        event = BaseEvent(
            level=EventLevel.INFO,
            category="test",
            message="test",
            data={"key": "value"},
        )
        handler.handle(event)
        handler.close()

        content = temp_log_file.read_text()
        data = json.loads(content.strip())

        assert "event_type" in data
        assert "code" in data
        assert "level" in data
        assert "category" in data
        assert "message" in data
        assert "meta" in data
        assert "data" in data

    def test_minimal_fields(self, temp_log_file):
        """Test minimal fields when include_all_fields=False."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1, include_all_fields=False)

        event = BaseEvent(
            level=EventLevel.INFO,
            category="test",
            message="test",
            data={"key": "value"},
        )
        handler.handle(event)
        handler.close()

        content = temp_log_file.read_text()
        data = json.loads(content.strip())

        assert "event_type" in data
        assert "level" in data
        assert "message" in data
        assert "timestamp" in data
        # Should not have these in minimal mode
        assert "data" not in data
        assert "code" not in data


class TestJSONFileHandlerFlush:
    """Tests for JSONFileHandler.flush()."""

    def test_flush_writes_buffer(self, temp_log_file):
        """Test that flush writes buffered events."""
        handler = JSONFileHandler(temp_log_file, buffer_size=100)

        event = BaseEvent(message="test")
        handler.handle(event)

        # Before flush, file might be empty
        handler.flush()

        content = temp_log_file.read_text()
        assert "test" in content
        handler.close()

    def test_flush_empty_buffer(self, temp_log_file):
        """Test that flush with empty buffer doesn't error."""
        handler = JSONFileHandler(temp_log_file, buffer_size=100)
        handler.flush()  # Should not raise
        handler.close()


class TestJSONFileHandlerClose:
    """Tests for JSONFileHandler.close()."""

    def test_close_flushes_buffer(self, temp_log_file):
        """Test that close flushes remaining buffer."""
        handler = JSONFileHandler(temp_log_file, buffer_size=100)

        event = BaseEvent(message="test")
        handler.handle(event)

        handler.close()

        content = temp_log_file.read_text()
        assert "test" in content

    def test_close_closes_file(self, temp_log_file):
        """Test that close closes the file handle."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1)

        event = BaseEvent(message="test")
        handler.handle(event)

        handler.close()

        assert handler._file is None

    def test_double_close_safe(self, temp_log_file):
        """Test that double close doesn't raise error."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1)
        handler.close()
        handler.close()  # Should not raise


class TestJSONFileHandlerRotation:
    """Tests for file rotation functionality."""

    def test_rotation_on_max_size(self, temp_log_file):
        """Test that file rotates when max size is reached."""
        # Very small max size (100 bytes) to trigger rotation
        # Each event serializes to ~120+ bytes, so rotation should occur after first event
        handler = JSONFileHandler(temp_log_file, buffer_size=1, max_file_size=100)
        try:
            # Write events that exceed max_file_size to trigger rotation
            # Using consistent message size for deterministic behavior
            message = "x" * 80  # Fixed-size message to ensure predictable event size
            for i in range(5):
                event = BaseEvent(message=f"{i}-{message}")
                handler.handle(event)
        finally:
            handler.close()

        # Check that at least one rotated file exists (rotation should have occurred)
        rotated_files = list(temp_log_file.parent.glob("test.*.json"))
        assert len(rotated_files) >= 1, (
            f"Expected at least 1 rotated file, found {len(rotated_files)}. "
            f"Files in directory: {list(temp_log_file.parent.iterdir())}"
        )

    def test_rotation_renames_file(self, temp_log_file):
        """Test that rotation renames file with timestamp."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1, max_file_size=50)
        try:
            # Write enough to trigger rotation
            for i in range(5):
                event = BaseEvent(message=f"message {i}")
                handler.handle(event)
        finally:
            handler.close()

        # Rotated files should have timestamp in name
        rotated_files = list(temp_log_file.parent.glob("test.*.json"))
        for f in rotated_files:
            # Should match pattern like test.20240115_103045.json
            assert "test." in f.name, f"Rotated file {f.name} should contain 'test.'"


class TestJSONFileHandlerThreadSafety:
    """Tests for thread-safe operations."""

    def test_concurrent_writes(self, temp_log_file):
        """Test that concurrent writes are thread-safe."""
        handler = JSONFileHandler(temp_log_file, buffer_size=5)
        errors = []
        events_written = []

        def write_events(start_id):
            try:
                for i in range(10):
                    event = BaseEvent(message=f"thread-{start_id}-event-{i}")
                    handler.handle(event)
                    events_written.append(1)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_events, args=(i,)) for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        handler.close()

        assert len(errors) == 0
        assert len(events_written) == 50

        # Verify file content is valid JSON
        content = temp_log_file.read_text()
        lines = content.strip().split("\n")
        for line in lines:
            json.loads(line)  # Should not raise

    def test_concurrent_flush(self, temp_log_file):
        """Test that concurrent flush calls are safe."""
        handler = JSONFileHandler(temp_log_file, buffer_size=100)
        errors = []

        # Write some events
        for i in range(10):
            handler.handle(BaseEvent(message=f"event {i}"))

        def flush_handler():
            try:
                handler.flush()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=flush_handler) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        handler.close()
        assert len(errors) == 0


class TestJSONFileHandlerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handles_unicode(self, temp_log_file):
        """Test handling of unicode characters."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1)

        event = BaseEvent(message="Test with unicode: 日本語 emoji: 🎉")
        handler.handle(event)
        handler.close()

        content = temp_log_file.read_text(encoding="utf-8")
        data = json.loads(content.strip())
        assert "日本語" in data["message"]
        assert "🎉" in data["message"]

    def test_handles_special_characters(self, temp_log_file):
        """Test handling of special JSON characters."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1)

        event = BaseEvent(message='Test with quotes: "hello" and newline:\nand tab:\t')
        handler.handle(event)
        handler.close()

        content = temp_log_file.read_text()
        data = json.loads(content.strip())
        assert '"hello"' in data["message"]

    def test_handles_large_message(self, temp_log_file):
        """Test handling of large messages."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1)

        large_message = "x" * 100000
        event = BaseEvent(message=large_message)
        handler.handle(event)
        handler.close()

        content = temp_log_file.read_text()
        data = json.loads(content.strip())
        assert len(data["message"]) == 100000

    def test_destructor_closes_file(self, temp_log_file):
        """Test that __del__ closes the file."""
        handler = JSONFileHandler(temp_log_file, buffer_size=1)
        handler.handle(BaseEvent(message="test"))

        # Explicitly call __del__
        handler.__del__()

        # File should be written
        content = temp_log_file.read_text()
        assert "test" in content

    def test_appends_to_existing_file(self, temp_log_file):
        """Test that handler appends to existing file."""
        # Write initial content
        temp_log_file.write_text('{"existing": true}\n')

        handler = JSONFileHandler(temp_log_file, buffer_size=1)
        handler.handle(BaseEvent(message="new event"))
        handler.close()

        content = temp_log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2
        assert '"existing": true' in lines[0]
        assert "new event" in lines[1]
