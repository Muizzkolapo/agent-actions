"""
Data models for batch processing.

Defines structured types for batch registry entries and related data.
"""

from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus


@dataclass
class BatchJobEntry:
    """
    Represents a single batch job entry in the registry.

    Attributes:
        batch_id: Unique identifier for the batch job
        status: Current status ('submitted', 'validating', 'in_progress',
                'finalizing', 'completed', 'failed', 'cancelled')
        timestamp: ISO format timestamp of creation
        provider: Provider type ('openai', 'gemini', 'anthropic')
        record_count: Number of records submitted in this batch
    """

    batch_id: str
    status: str
    timestamp: str
    provider: str
    record_count: Optional[int] = None
    workflow_session_id: Optional[str] = None
    file_name: Optional[str] = None
    # Version context fields for loop correlation
    is_versioned_agent: Optional[bool] = None
    version_base_name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "BatchJobEntry":
        """Create BatchJobEntry from dictionary (JSON deserialization)."""
        return cls(**data)

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
    """
    Aggregated statistics for all batches in registry.

    Used by get_overall_status() and reporting.
    """

    total_jobs: int
    completed: int
    failed: int
    in_progress: int
    cancelled: int

    @property
    def overall_status(self) -> str:
        """
        Get overall status across all jobs.

        Returns:
            'no_batches', 'completed', 'in_progress', 'partial_failed', 'error'
        """
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
    """
    Result of filtering a single item.

    Attributes:
        status: Filter status ('included', 'skipped', 'filtered')
        should_include: Whether item should be included in batch
        reason: Reason for the filtering decision
        metadata: Additional filtering metadata
    """

    status: str
    should_include: bool
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchTaskPreparationStats:
    """
    Statistics from batch task preparation.

    Tracks what happened during task preparation for monitoring and debugging.

    Attributes:
        total_items: Total items provided
        included_items: Items included in batch
        filtered_items: Items filtered out (WHERE clause with behavior='filter')
        skipped_items: Items skipped (WHERE clause with behavior='skip')
        error_items: Items that failed during preparation
    """

    total_items: int = 0
    included_items: int = 0
    filtered_items: int = 0
    skipped_items: int = 0
    error_items: int = 0

    @property
    def success_rate(self) -> float:
        """Calculate success rate (included / total)."""
        if self.total_items == 0:
            return 0.0
        return self.included_items / self.total_items


@dataclass
class PreparedBatchTasks:
    """
    Result of batch task preparation.

    Immutable result returned by BatchTaskPreparator.prepare_tasks().
    Contains everything needed for batch submission.

    Attributes:
        tasks: Provider-ready batch tasks
        context_map: Mapping of custom_id -> original row data with metadata
        stats: Preparation statistics
        config: Agent configuration used for preparation
    """

    tasks: List[Dict[str, Any]]
    context_map: Dict[str, Any]
    stats: BatchTaskPreparationStats
    config: Optional[Dict[str, Any]] = None

    @property
    def is_empty(self) -> bool:
        """Check if no tasks were prepared."""
        return len(self.tasks) == 0

    @property
    def task_count(self) -> int:
        """Get number of prepared tasks."""
        return len(self.tasks)
