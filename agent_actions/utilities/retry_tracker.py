"""
Retry event tracking module.

Provides centralized tracking of retry events for both online and batch modes.
Persists retry events with full record data to enable debugging and analysis.

Usage:
    from agent_actions.utilities.retry_tracker import RetryTracker

    # Initialize tracker (typically once per workflow run)
    tracker = RetryTracker(output_directory="/path/to/agent_io")

    # Log a retry attempt
    tracker.log_retry(
        action="classify_genre",
        mode="online",
        attempt=1,
        max_attempts=3,
        error_type="RateLimitError",
        error_message="Rate limit exceeded",
        record={"source_guid": "123", "title": "Book Title", ...},
    )

    # Mark retry as successful
    tracker.mark_success(entry_id)

    # Get summary statistics
    summary = tracker.get_summary()
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Retry log filename
RETRY_LOG_FILENAME = ".retry_log.json"


class RetryEntry:
    """Represents a single retry event."""

    def __init__(
        self,
        action: str,
        mode: str,
        attempt: int,
        max_attempts: int,
        error_type: str,
        error_message: str,
        record: Dict[str, Any],
        entry_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        outcome: str = "pending",
        target_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ):
        """
        Initialize retry entry.

        Args:
            action: Action/agent name being retried
            mode: "online" or "batch"
            attempt: Current attempt number (1-indexed)
            max_attempts: Maximum retry attempts configured
            error_type: Type of error that triggered retry
            error_message: Error message
            record: Full record data being processed
            entry_id: Unique ID (auto-generated if not provided)
            timestamp: ISO timestamp (auto-generated if not provided)
            outcome: "pending", "success", or "exhausted"
            target_id: Target ID of the output record (set after processing)
            node_id: Node ID of the output record (set after processing)
        """
        self.id = entry_id or str(uuid.uuid4())[:8]
        self.timestamp = timestamp or datetime.now().isoformat()
        self.action = action
        self.mode = mode
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.error_type = error_type
        self.error_message = error_message
        self.record = record
        self.outcome = outcome
        self.target_id = target_id
        self.node_id = node_id

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action,
            "mode": self.mode,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "record": self.record,
            "outcome": self.outcome,
        }
        # Only include target_id and node_id if set
        if self.target_id is not None:
            result["target_id"] = self.target_id
        if self.node_id is not None:
            result["node_id"] = self.node_id
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryEntry":
        """Create from dictionary."""
        return cls(
            entry_id=data.get("id"),
            timestamp=data.get("timestamp"),
            action=data["action"],
            mode=data["mode"],
            attempt=data["attempt"],
            max_attempts=data["max_attempts"],
            error_type=data["error_type"],
            error_message=data["error_message"],
            record=data["record"],
            outcome=data.get("outcome", "pending"),
            target_id=data.get("target_id"),
            node_id=data.get("node_id"),
        )


class RetryTracker:
    """
    Centralized retry event tracker with file persistence.

    Tracks retry events for both online and batch modes, persisting
    full record data to enable debugging and analysis.

    Thread-safe: Uses locking for concurrent access.
    """

    # Singleton instance per output directory
    _instances: Dict[str, "RetryTracker"] = {}
    _instance_lock = Lock()

    def __new__(cls, output_directory: str) -> "RetryTracker":
        """Get or create singleton instance per output directory."""
        output_directory = str(Path(output_directory).resolve())

        with cls._instance_lock:
            if output_directory not in cls._instances:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instances[output_directory] = instance
            return cls._instances[output_directory]

    def __init__(self, output_directory: str):
        """
        Initialize retry tracker.

        Args:
            output_directory: Directory to store retry log file
        """
        # Only initialize once per instance
        if getattr(self, "_initialized", False):
            return

        self._output_directory = Path(output_directory).resolve()
        self._log_file = self._output_directory / RETRY_LOG_FILENAME
        self._lock = Lock()
        self._entries: List[RetryEntry] = []
        self._run_id: Optional[str] = None
        self._workflow_name: Optional[str] = None
        self._created_at: Optional[str] = None

        # Load existing log if present
        self._load()
        self._initialized = True

    def _load(self) -> None:
        """Load existing retry log from file."""
        if not self._log_file.exists():
            return

        try:
            with open(self._log_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._run_id = data.get("run_id")
            self._workflow_name = data.get("workflow_name")
            self._created_at = data.get("created_at")
            self._entries = [RetryEntry.from_dict(entry) for entry in data.get("entries", [])]

            logger.debug("Loaded %d retry entries from %s", len(self._entries), self._log_file)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Could not load retry log: %s", e)
            self._entries = []

    def _save(self) -> None:
        """Persist retry log to file."""
        try:
            self._output_directory.mkdir(parents=True, exist_ok=True)

            data = {
                "run_id": self._run_id,
                "workflow_name": self._workflow_name,
                "created_at": self._created_at or datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "summary": self._compute_summary(),
                "entries": [entry.to_dict() for entry in self._entries],
            }

            with open(self._log_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            logger.debug("Saved %d retry entries to %s", len(self._entries), self._log_file)
        except (OSError, IOError, TypeError) as e:
            logger.error("Failed to save retry log: %s", e)

    def _compute_summary(self) -> Dict[str, Any]:
        """Compute summary statistics."""
        total = len(self._entries)
        successful = sum(1 for e in self._entries if e.outcome == "success")
        exhausted = sum(1 for e in self._entries if e.outcome == "exhausted")
        pending = sum(1 for e in self._entries if e.outcome == "pending")

        # Group by action
        by_action: Dict[str, Dict[str, int]] = {}
        for entry in self._entries:
            if entry.action not in by_action:
                by_action[entry.action] = {"total": 0, "success": 0, "exhausted": 0}
            by_action[entry.action]["total"] += 1
            if entry.outcome == "success":
                by_action[entry.action]["success"] += 1
            elif entry.outcome == "exhausted":
                by_action[entry.action]["exhausted"] += 1

        return {
            "total_retries": total,
            "successful_retries": successful,
            "exhausted_retries": exhausted,
            "pending_retries": pending,
            "by_action": by_action,
        }

    def set_run_context(self, run_id: str, workflow_name: str) -> None:
        """
        Set run context for the tracker.

        Args:
            run_id: Unique run identifier
            workflow_name: Name of the workflow
        """
        with self._lock:
            self._run_id = run_id
            self._workflow_name = workflow_name
            self._created_at = datetime.now().isoformat()
            self._save()

    def log_retry(
        self,
        action: str,
        mode: str,
        attempt: int,
        max_attempts: int,
        error_type: str,
        error_message: str,
        record: Dict[str, Any],
    ) -> str:
        """
        Log a retry event.

        Args:
            action: Action/agent name being retried
            mode: "online" or "batch"
            attempt: Current attempt number (1-indexed)
            max_attempts: Maximum retry attempts configured
            error_type: Type of error that triggered retry
            error_message: Error message
            record: Full record data being processed

        Returns:
            Entry ID for later updates
        """
        entry = RetryEntry(
            action=action,
            mode=mode,
            attempt=attempt,
            max_attempts=max_attempts,
            error_type=error_type,
            error_message=error_message,
            record=record,
        )

        with self._lock:
            self._entries.append(entry)
            self._save()

        logger.info(
            "Retry logged: action=%s, mode=%s, attempt=%d/%d, error=%s",
            action,
            mode,
            attempt,
            max_attempts,
            error_type,
        )

        return entry.id

    def mark_success(self, entry_id: str) -> bool:
        """
        Mark a retry entry as successful.

        Args:
            entry_id: Entry ID to update

        Returns:
            True if entry was found and updated
        """
        with self._lock:
            for entry in self._entries:
                if entry.id == entry_id:
                    entry.outcome = "success"
                    self._save()
                    logger.debug("Retry entry %s marked as success", entry_id)
                    return True
        return False

    def mark_exhausted(self, entry_id: str) -> bool:
        """
        Mark a retry entry as exhausted (max retries reached).

        Args:
            entry_id: Entry ID to update

        Returns:
            True if entry was found and updated
        """
        with self._lock:
            for entry in self._entries:
                if entry.id == entry_id:
                    entry.outcome = "exhausted"
                    self._save()
                    logger.debug("Retry entry %s marked as exhausted", entry_id)
                    return True
        return False

    def update_entry_ids(
        self,
        entry_id: str,
        target_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> bool:
        """
        Update an entry with target_id and node_id after they are known.

        This is called after LLM response is processed and IDs are generated,
        enabling correlation between retry log entries and output records.

        Args:
            entry_id: Entry ID to update
            target_id: The target_id of the output record
            node_id: The node_id of the output record

        Returns:
            True if entry was found and updated
        """
        with self._lock:
            for entry in self._entries:
                if entry.id == entry_id:
                    if target_id is not None:
                        entry.target_id = target_id
                    if node_id is not None:
                        entry.node_id = node_id
                    self._save()
                    logger.debug(
                        "Retry entry %s updated with target_id=%s, node_id=%s",
                        entry_id,
                        target_id,
                        node_id,
                    )
                    return True
        return False

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics.

        Returns:
            Dictionary with summary counts and breakdown by action
        """
        with self._lock:
            return self._compute_summary()

    def get_entries(
        self,
        action: Optional[str] = None,
        mode: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get retry entries with optional filtering.

        Args:
            action: Filter by action name
            mode: Filter by mode ("online" or "batch")
            outcome: Filter by outcome ("pending", "success", "exhausted")

        Returns:
            List of entry dictionaries
        """
        with self._lock:
            entries = self._entries.copy()

        if action:
            entries = [e for e in entries if e.action == action]
        if mode:
            entries = [e for e in entries if e.mode == mode]
        if outcome:
            entries = [e for e in entries if e.outcome == outcome]

        return [e.to_dict() for e in entries]

    def clear(self) -> None:
        """Clear all entries and remove log file."""
        with self._lock:
            self._entries = []
            if self._log_file.exists():
                self._log_file.unlink()
            logger.debug("Retry log cleared")

    @classmethod
    def reset_instances(cls) -> None:
        """Reset all singleton instances (for testing)."""
        with cls._instance_lock:
            cls._instances.clear()


def get_retry_tracker(output_directory: str) -> RetryTracker:
    """
    Get or create retry tracker for an output directory.

    Convenience function for getting the singleton tracker instance.

    Args:
        output_directory: Directory to store retry log

    Returns:
        RetryTracker instance
    """
    return RetryTracker(output_directory)


# Thread-local storage for current tracker context
import threading

_current_tracker_context = threading.local()


def set_current_retry_tracker(tracker: Optional[RetryTracker]) -> None:
    """
    Set the current retry tracker for this thread.

    Used by workflow orchestration to establish a tracker context
    that lower-level code can access without explicit parameter passing.

    Args:
        tracker: RetryTracker instance or None to clear
    """
    _current_tracker_context.tracker = tracker


def get_current_retry_tracker() -> Optional[RetryTracker]:
    """
    Get the current retry tracker for this thread.

    Returns:
        RetryTracker instance if set, None otherwise
    """
    return getattr(_current_tracker_context, "tracker", None)


class RetryTrackerContext:
    """
    Context manager for setting up retry tracking.

    Usage:
        with RetryTrackerContext(output_directory="/path/to/agent_io") as tracker:
            # Lower-level code can now use get_current_retry_tracker()
            run_workflow()
    """

    def __init__(
        self,
        output_directory: str,
        run_id: Optional[str] = None,
        workflow_name: Optional[str] = None,
    ):
        """
        Initialize retry tracker context.

        Args:
            output_directory: Directory for retry log file
            run_id: Optional run identifier
            workflow_name: Optional workflow name
        """
        self._output_directory = output_directory
        self._run_id = run_id
        self._workflow_name = workflow_name
        self._tracker: Optional[RetryTracker] = None
        self._previous_tracker: Optional[RetryTracker] = None

    def __enter__(self) -> RetryTracker:
        """Enter context and set up tracker."""
        self._previous_tracker = get_current_retry_tracker()
        self._tracker = get_retry_tracker(self._output_directory)

        if self._run_id or self._workflow_name:
            self._tracker.set_run_context(
                run_id=self._run_id or "unknown",
                workflow_name=self._workflow_name or "unknown",
            )

        set_current_retry_tracker(self._tracker)
        return self._tracker

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        """Exit context and restore previous tracker."""
        set_current_retry_tracker(self._previous_tracker)
        return False
