"""JSON file handler that writes events as newline-delimited JSON."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


class JSONFileHandler:
    """Handler that writes events as NDJSON to a file with buffering and optional rotation."""

    def __init__(
        self,
        file_path: str | Path,
        min_level: Any | None = None,
        buffer_size: int = 10,
        max_file_size: int | None = None,
        include_all_fields: bool = True,
    ) -> None:
        """Initialize the JSON file handler."""
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

        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        if self.file_path.exists():
            self._current_size = self.file_path.stat().st_size

    def accepts(self, event: BaseEvent) -> bool:
        """Check if this event meets the minimum level threshold."""
        from agent_actions.logging.core.events import EventLevel

        level_order = EventLevel.ordered()
        return level_order.index(event.level) >= level_order.index(self.min_level)

    def handle(self, event: BaseEvent) -> None:
        """Buffer the event for writing to the JSON log file."""
        if self.include_all_fields:
            event_dict = event.to_dict()
        else:
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

        if self.max_file_size and self._current_size >= self.max_file_size:
            self._rotate()

        if self._file is None:
            self._file = open(self.file_path, "a", encoding="utf-8")
            self._current_size = self.file_path.stat().st_size if self.file_path.exists() else 0

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

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
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
