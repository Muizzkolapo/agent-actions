"""Data models for batch processing registry entries and task preparation."""

import dataclasses
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from agent_actions.llm.batch.core.batch_constants import BatchStatus


@dataclass
class BatchJobEntry:
    """A single batch job entry in the registry."""

    batch_id: str
    status: str
    timestamp: str
    provider: str
    record_count: int | None = None
    workflow_session_id: str | None = None
    file_name: str | None = None
    # Version context fields for loop correlation
    is_versioned_agent: bool | None = None
    version_base_name: str | None = None
    # Recovery fields for async retry/reprompt batches
    parent_file_name: str | None = None  # links to original batch's file_name key
    recovery_type: Literal["retry", "reprompt"] | None = None
    recovery_attempt: int | None = None  # attempt number (1, 2, 3...)

    def __post_init__(self):
        """Warn on unrecognized status to avoid breaking existing registries."""
        valid = {s.value for s in BatchStatus}
        if self.status not in valid:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "Unrecognized batch status '%s'. Expected one of: %s",
                self.status,
                ", ".join(sorted(valid)),
            )

    @classmethod
    def from_dict(cls, data: dict) -> "BatchJobEntry":
        """Create BatchJobEntry from dictionary (JSON deserialization)."""
        known_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @property
    def is_terminal(self) -> bool:
        """Check if batch is in terminal state (completed/failed/cancelled)."""
        return self.status in BatchStatus.terminal_states()

    @property
    def is_in_flight(self) -> bool:
        """Check if batch is still in progress."""
        return self.status in BatchStatus.in_flight_states()


@dataclass
class BatchRegistryStats:
    """Aggregated statistics for all batches in registry."""

    total_jobs: int
    completed: int
    failed: int
    in_progress: int
    cancelled: int

    @property
    def overall_status(self) -> str:
        """Get overall status across all jobs."""
        if self.total_jobs == 0:
            return "no_batches"

        if self.completed == self.total_jobs:
            return "completed"

        if self.failed > 0:
            return "partial_failed"

        if self.in_progress > 0:
            return "in_progress"

        return "error"


# Phase 4 Models: Task Preparation


@dataclass
class BatchFilterResult:
    """Result of filtering a single item."""

    status: str
    should_include: bool
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchTaskPreparationStats:
    """Statistics from batch task preparation across both filter phases."""

    total_items: int = 0
    included_items: int = 0
    filtered_items: int = 0
    skipped_items: int = 0
    phase2_filtered_items: int = 0
    phase2_skipped_items: int = 0
    error_items: int = 0

    @property
    def total_filtered(self) -> int:
        """Total items filtered across both phases."""
        return self.filtered_items + self.phase2_filtered_items

    @property
    def total_skipped(self) -> int:
        """Total items skipped across both phases."""
        return self.skipped_items + self.phase2_skipped_items

    @property
    def success_rate(self) -> float:
        """Calculate success rate (included / total)."""
        if self.total_items == 0:
            return 0.0
        return self.included_items / self.total_items


@dataclass
class PreparedBatchTasks:
    """Immutable result of BatchTaskPreparator.prepare_tasks()."""

    tasks: list[dict[str, Any]]
    context_map: dict[str, Any]
    stats: BatchTaskPreparationStats
    config: dict[str, Any] | None = None

    @property
    def is_empty(self) -> bool:
        """Check if no tasks were prepared."""
        return len(self.tasks) == 0

    @property
    def task_count(self) -> int:
        """Get number of prepared tasks."""
        return len(self.tasks)


@dataclass
class SubmissionResult:
    """Result of a batch submission."""

    batch_id: str | None = None
    passthrough: dict[str, Any] | None = None

    @property
    def is_submitted(self) -> bool:
        return self.batch_id is not None

    @property
    def is_passthrough(self) -> bool:
        return self.passthrough is not None
