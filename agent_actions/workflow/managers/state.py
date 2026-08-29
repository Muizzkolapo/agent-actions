"""Action workflow state management for execution status persistence."""

import json
import logging
import threading
from collections.abc import Container
from enum import Enum
from pathlib import Path
from typing import Any

from agent_actions.utils.atomic_write import atomic_json_write

logger = logging.getLogger(__name__)


class ActionStatus(str, Enum):
    """Action lifecycle statuses.

    Using str mixin so enum values serialize as plain strings in JSON
    and compare equal to their string values for backward compatibility.
    """

    PENDING = "pending"
    RUNNING = "running"
    BATCH_SUBMITTED = "batch_submitted"
    CHECKING_BATCH = "checking_batch"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED = "failed"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


# Status sets used across the workflow engine. Import from here to avoid
# scattered set literals that drift when new statuses are added.
COMPLETED_STATUSES: frozenset[ActionStatus] = frozenset(
    {ActionStatus.COMPLETED, ActionStatus.COMPLETED_WITH_FAILURES}
)
TERMINAL_STATUSES: frozenset[ActionStatus] = frozenset(
    {
        ActionStatus.COMPLETED,
        ActionStatus.FAILED,
        ActionStatus.SKIPPED,
        ActionStatus.COMPLETED_WITH_FAILURES,
        ActionStatus.INTERRUPTED,
    }
)
RETRYABLE_STATUSES: frozenset[ActionStatus] = frozenset(
    {
        ActionStatus.FAILED,
        ActionStatus.SKIPPED,
        ActionStatus.RUNNING,
        ActionStatus.CHECKING_BATCH,
        ActionStatus.INTERRUPTED,
    }
)
# Statuses whose action died mid-processing and may hold checkpointed SUCCESS
# dispositions. _reset_retryable_actions must clear these selectively, never in
# bulk, or resume reprocesses work that already succeeded.
MID_PROCESSING_STATUSES: frozenset[ActionStatus] = frozenset(
    {ActionStatus.RUNNING, ActionStatus.INTERRUPTED}
)


class ActionStateManager:
    """Manages action execution state persistence and queries."""

    def __init__(self, status_file_path: Path, execution_order: list[str]):
        """Initialize state manager."""
        self.status_file = status_file_path
        self.execution_order = execution_order
        self.action_status: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load_status()

    def _load_status(self):
        """Load action status from file, or initialize with defaults."""
        if self.status_file.exists():
            try:
                with open(self.status_file, encoding="utf-8") as f:
                    self.action_status = json.load(f)
                logger.info("Loaded status for %d actions", len(self.action_status))
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.warning("Could not load status file: %s", e)
                self._initialize_default_status()
        else:
            self._initialize_default_status()

    def reset(self) -> None:
        """Reset all actions to 'pending' status and persist."""
        with self._lock:
            self._initialize_default_status()
            self._save_status()

    def _initialize_default_status(self):
        """Initialize all actions with 'pending' status."""
        self.action_status = {
            action: {"status": ActionStatus.PENDING} for action in self.execution_order
        }

    def _save_status(self):
        """Persist current status to file. Raises on I/O failure."""
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self.status_file, self.action_status, indent=4)

    def update_status(self, action_name: str, status: ActionStatus, **metadata):
        """Update action status and persist to file."""
        with self._lock:
            if action_name not in self.action_status:
                self.action_status[action_name] = {}

            self.action_status[action_name]["status"] = status

            for key, value in metadata.items():
                self.action_status[action_name][key] = value

            self._save_status()

    def get_status(self, action_name: str) -> ActionStatus:
        """Return current status of an action, defaulting to PENDING."""
        raw = self.action_status.get(action_name, {}).get("status", ActionStatus.PENDING)
        return ActionStatus(raw)

    def get_status_details(self, action_name: str) -> dict[str, Any]:
        """Return full status details for an action."""
        return self.action_status.get(action_name, {"status": ActionStatus.PENDING})

    def is_completed(self, action_name: str) -> bool:
        """Return True if action completed (including partial failures)."""
        return self.get_status(action_name) in COMPLETED_STATUSES

    def is_batch_submitted(self, action_name: str) -> bool:
        """Return True if action has batch jobs submitted."""
        return self.get_status(action_name) == ActionStatus.BATCH_SUBMITTED

    def is_failed(self, action_name: str) -> bool:
        """Return True if action has failed."""
        return self.get_status(action_name) == ActionStatus.FAILED

    def is_skipped(self, action_name: str) -> bool:
        """Return True if action was skipped due to upstream dependency failure."""
        return self.get_status(action_name) == ActionStatus.SKIPPED

    def is_completed_with_failures(self, action_name: str) -> bool:
        """Return True if action completed with partial item failures."""
        return self.get_status(action_name) == ActionStatus.COMPLETED_WITH_FAILURES

    def is_terminal(self, action_name: str) -> bool:
        """Return True if action is in a terminal state (no further transitions)."""
        return self.get_status(action_name) in TERMINAL_STATUSES

    def is_in_progress(self, action_name: str) -> bool:
        """Return True if action has started but not reached a terminal state."""
        status = self.get_status(action_name)
        return status not in TERMINAL_STATUSES and status != ActionStatus.PENDING

    def get_pending_actions(self, agents: list[str]) -> list[str]:
        """Return actions that are not yet in a terminal state (runnable)."""
        return [agent for agent in agents if self.get_status(agent) not in TERMINAL_STATUSES]

    def get_batch_submitted_actions(self, agents: list[str]) -> list[str]:
        """Return actions with batch jobs submitted."""
        return [agent for agent in agents if self.is_batch_submitted(agent)]

    def get_failed_actions(self, agents: list[str]) -> list[str]:
        """Return actions that have failed."""
        return [agent for agent in agents if self.is_failed(agent)]

    def get_skipped_actions(self, agents: list[str]) -> list[str]:
        """Return actions that were skipped."""
        return [agent for agent in agents if self.is_skipped(agent)]

    def _bulk_transition(
        self,
        from_statuses: frozenset[ActionStatus] | set[ActionStatus],
        to_status: ActionStatus,
        exclude: Container[str] = (),
    ) -> list[str]:
        """Transition all actions matching *from_statuses* to *to_status*.

        Holds the lock for the entire scan-mutate-save cycle and persists
        at most once.  Returns the names of affected actions.
        """
        with self._lock:
            affected = [
                name
                for name, details in self.action_status.items()
                if details.get("status") in from_statuses and name not in exclude
            ]
            for name in affected:
                self.action_status[name]["status"] = to_status
            if affected:
                self._save_status()
        return affected

    def _mark_running_as(self, status: ActionStatus) -> list[str]:
        """Transition in-flight actions to *status*, returning the names swept.

        BATCH_SUBMITTED is deliberately excluded: that work continues in the
        provider's queue after this process exits, so it is not in flight here.
        """
        return self._bulk_transition({ActionStatus.RUNNING, ActionStatus.CHECKING_BATCH}, status)

    def mark_running_as_failed(self) -> list[str]:
        """Mark all actions in 'running' or 'checking_batch' status as failed."""
        return self._mark_running_as(ActionStatus.FAILED)

    def mark_running_as_interrupted(self) -> list[str]:
        """Mark in-flight actions as interrupted when the run is killed.

        Distinct from FAILED: the action did not produce a bad result, it never
        finished. _reset_retryable_actions relies on that difference to preserve
        checkpointed SUCCESS dispositions on resume.
        """
        return self._mark_running_as(ActionStatus.INTERRUPTED)

    def reset_retryable(self, exclude: Container[str] = ()) -> list[str]:
        """Reset retryable actions to PENDING for re-run.

        Called at workflow startup so that re-runs retry failed, skipped,
        in-progress, and partially-failed actions while preserving fully
        completed results.  Callers should clear storage dispositions for
        the returned action names, and name in *exclude* any action whose
        state must be preserved rather than retried.
        """
        return self._bulk_transition(RETRYABLE_STATUSES, ActionStatus.PENDING, exclude=exclude)

    def get_summary(self) -> dict[str, int]:
        """Return summary counts of action statuses (current actions only)."""
        summary: dict[str, int] = {}
        for name in self.execution_order:
            status = self.action_status.get(name, {}).get("status", ActionStatus.PENDING)
            summary[status] = summary.get(status, 0) + 1
        return summary

    def is_workflow_complete(self) -> bool:
        """Return True if all current actions completed (including partial failures)."""
        return all(
            self.action_status.get(name, {}).get("status") in COMPLETED_STATUSES
            for name in self.execution_order
        )

    def is_workflow_done(self) -> bool:
        """Return True if all current actions are in a terminal state."""
        return all(
            self.action_status.get(name, {}).get("status") in TERMINAL_STATUSES
            for name in self.execution_order
        )

    def has_any_failed(self) -> bool:
        """Return True if any current action has 'failed' status."""
        return any(
            self.action_status.get(name, {}).get("status") == ActionStatus.FAILED
            for name in self.execution_order
        )
