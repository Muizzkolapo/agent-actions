"""Action workflow state management for execution status persistence."""

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any

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
    }
)


class ActionStateManager:
    """Manages action execution state persistence and queries."""

    def __init__(self, status_file_path: Path, execution_order: list[str]):
        """Initialize state manager."""
        self.status_file = status_file_path
        self.execution_order = execution_order
        self.action_status: dict[str, dict[str, Any]] = {}
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
        self._initialize_default_status()
        self._save_status()

    def _initialize_default_status(self):
        """Initialize all actions with 'pending' status."""
        self.action_status = {
            action: {"status": ActionStatus.PENDING} for action in self.execution_order
        }

    def _save_status(self):
        """Persist current status to file."""
        try:
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(self.action_status, f, indent=4)
        except (OSError, ValueError, TypeError) as e:
            logger.error("Error saving status: %s", e)

    def update_status(self, action_name: str, status: ActionStatus, **metadata):
        """Update action status and persist to file."""
        if action_name not in self.action_status:
            self.action_status[action_name] = {}

        self.action_status[action_name]["status"] = status

        # Add any additional metadata
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

    def mark_running_as_failed(self) -> list[str]:
        """Mark all actions in 'running' or 'checking_batch' status as failed.

        Returns list of action names that were marked failed.
        """
        marked: list[str] = []
        for action_name, details in self.action_status.items():
            if details.get("status") in (ActionStatus.RUNNING, ActionStatus.CHECKING_BATCH):
                marked.append(action_name)
        for action_name in marked:
            self.update_status(action_name, ActionStatus.FAILED)
        return marked

    def get_summary(self) -> dict[str, int]:
        """Return summary counts of action statuses."""
        summary: dict[str, int] = {}
        for details in self.action_status.values():
            status = details.get("status", ActionStatus.PENDING)
            summary[status] = summary.get(status, 0) + 1
        return summary

    def is_workflow_complete(self) -> bool:
        """Return True if all actions completed (including partial failures)."""
        return all(
            details.get("status") in COMPLETED_STATUSES for details in self.action_status.values()
        )

    def is_workflow_done(self) -> bool:
        """Return True if all actions are in a terminal state."""
        return all(
            details.get("status") in TERMINAL_STATUSES for details in self.action_status.values()
        )

    def has_any_failed(self) -> bool:
        """Return True if any action has 'failed' status."""
        return any(
            details.get("status") == ActionStatus.FAILED for details in self.action_status.values()
        )
