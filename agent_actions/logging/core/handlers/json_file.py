"""JSON file handler that writes events as newline-delimited JSON."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent

logger = logging.getLogger(__name__)

RUN_LOG_NAMES: tuple[str, ...] = ("events", "errors")


def rotate_run_logs(logs_dir: Path, keep: int) -> None:
    """Shift each run log one slot back (events.json -> events.1.json) and drop slot *keep*."""
    for name in RUN_LOG_NAMES:
        current = logs_dir / f"{name}.json"
        slots = [current] + [logs_dir / f"{name}.{k}.json" for k in range(1, keep + 1)]
        try:
            slots[-1].unlink(missing_ok=True)
            for older, newer in zip(reversed(slots[1:]), reversed(slots[:-1]), strict=True):
                if newer.exists():
                    newer.rename(older)
        except OSError as e:
            logger.warning("Could not rotate %s in %s: %s", name, logs_dir, e)


class JSONFileHandler:
    """Handler that writes events as NDJSON to a file, shedding DEBUG rows past an optional cap."""

    def __init__(
        self,
        file_path: str | Path,
        min_level: Any | None = None,
        buffer_size: int = 10,
        max_debug_bytes: int | None = None,
        include_all_fields: bool = True,
    ) -> None:
        """Initialize the JSON file handler."""
        from agent_actions.logging.core.events import EventLevel

        self.file_path = Path(file_path)
        self.min_level = min_level or EventLevel.DEBUG
        self.buffer_size = buffer_size
        self.max_debug_bytes = max_debug_bytes
        self._shedding = False
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
        from agent_actions.logging.core.events import EventLevel

        if self.max_debug_bytes and event.level is EventLevel.DEBUG:
            with self._lock:
                if self._current_size + self._buffered_bytes() >= self.max_debug_bytes:
                    if not self._shedding:
                        self._shedding = True
                        self._buffer.append(self._cap_event(event).to_dict())
                    return

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

        if self._file is None:
            self._file = open(self.file_path, "a", encoding="utf-8")
            self._current_size = self.file_path.stat().st_size if self.file_path.exists() else 0

        written = 0
        try:
            for event_dict in self._buffer:
                line = json.dumps(event_dict, default=str) + "\n"
                self._file.write(line)
                self._current_size += len(line.encode("utf-8"))
                written += 1
        finally:
            if written > 0:
                del self._buffer[:written]

    def _buffered_bytes(self) -> int:
        """Approximate size of buffered rows; the buffer holds at most ``buffer_size`` events."""
        return sum(len(json.dumps(row, default=str)) + 1 for row in self._buffer)

    def _cap_event(self, event: BaseEvent) -> BaseEvent:
        from agent_actions.logging.events.io_events import LogFileCapReachedEvent

        cap = LogFileCapReachedEvent(
            file_name=self.file_path.name, max_bytes=self.max_debug_bytes or 0
        )
        cap.meta.invocation_id = event.meta.invocation_id
        cap.meta.correlation_id = event.meta.correlation_id
        return cap

    def __del__(self) -> None:
        """Cleanup on deletion."""
        try:
            self.close()
        except Exception:
            pass
