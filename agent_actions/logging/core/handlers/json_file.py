"""
JSON file handler for event logging.

Writes events as newline-delimited JSON (NDJSON) to a log file.
This format is ideal for log aggregation and analysis tools.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


class JSONFileHandler:
    """
    Handler that writes events as JSON to a file.

    Events are written as newline-delimited JSON (NDJSON), where each
    line is a complete JSON object representing one event.

    Features:
        - Thread-safe file writes
        - Automatic file rotation by size (optional)
        - Buffered writes for performance
        - Automatic directory creation

    Output format (one event per line):
        {"event_type": "WorkflowStart", "level": "info", "message": "...", ...}
        {"event_type": "AgentComplete", "level": "info", "message": "...", ...}
    """

    def __init__(
        self,
        file_path: str | Path,
        min_level: Any | None = None,
        buffer_size: int = 10,
        max_file_size: int | None = None,
        include_all_fields: bool = True,
    ) -> None:
        """
        Initialize the JSON file handler.

        Args:
            file_path: Path to the log file
            min_level: Minimum event level to log (default: DEBUG - log everything)
            buffer_size: Number of events to buffer before flushing
            max_file_size: Max file size in bytes before rotation (None = no rotation)
            include_all_fields: Whether to include all event fields or just basics
        """
        from agent_actions.logging.core.events import EventLevel

        self.file_path = Path(file_path)
        self.min_level = min_level or EventLevel.DEBUG
        self.buffer_size = buffer_size
        self.max_file_size = max_file_size
        self.include_all_fields = include_all_fields

        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._file: TextIO | None = None
        self._current_size = 0

        # Ensure directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def accepts(self, event: BaseEvent) -> bool:
        """
        Check if this event should be logged.

        Args:
            event: Event to check

        Returns:
            True if event should be logged
        """
        from agent_actions.logging.core.events import EventLevel

        level_order = [EventLevel.DEBUG, EventLevel.INFO, EventLevel.WARN, EventLevel.ERROR]
        return level_order.index(event.level) >= level_order.index(self.min_level)

    def handle(self, event: BaseEvent) -> None:
        """
        Write the event to the JSON log file.

        Events are buffered and written in batches for performance.

        Args:
            event: Event to log
        """
        # Convert event to dict
        if self.include_all_fields:
            event_dict = event.to_dict()
        else:
            # Minimal fields
            event_dict = {
                "event_type": event.event_type,
                "level": event.level.value,
                "message": event.message,
                "timestamp": event.meta.timestamp.isoformat()
                if isinstance(event.meta.timestamp, datetime)
                else str(event.meta.timestamp),
            }

        with self._lock:
            self._buffer.append(event_dict)

            if len(self._buffer) >= self.buffer_size:
                self._flush_buffer()

    def flush(self) -> None:
        """Flush all buffered events to disk."""
        with self._lock:
            self._flush_buffer()
            if self._file:
                self._file.flush()

    def close(self) -> None:
        """Close the log file."""
        self.flush()
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None

    def _flush_buffer(self) -> None:
        """Write buffered events to file (must hold lock)."""
        if not self._buffer:
            return

        # Check for rotation
        if self.max_file_size and self._current_size >= self.max_file_size:
            self._rotate()

        # Open file if needed
        if self._file is None:
            self._file = open(self.file_path, "a", encoding="utf-8")
            self._current_size = self.file_path.stat().st_size if self.file_path.exists() else 0

        # Write events
        for event_dict in self._buffer:
            line = json.dumps(event_dict, default=str) + "\n"
            self._file.write(line)
            self._current_size += len(line.encode("utf-8"))

        self._buffer.clear()

    def _rotate(self) -> None:
        """Rotate the log file (must hold lock)."""
        if self._file:
            self._file.close()
            self._file = None

        # Rename current file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rotated_path = self.file_path.with_suffix(f".{timestamp}.json")

        if self.file_path.exists():
            self.file_path.rename(rotated_path)

        self._current_size = 0

    def __del__(self) -> None:
        """Cleanup on deletion."""
        try:
            self.close()
        except Exception:
            pass
