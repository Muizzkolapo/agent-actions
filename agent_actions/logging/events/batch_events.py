"""Batch processing events (B prefix)."""

from dataclasses import dataclass

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories

__all__ = [
    "BatchSubmittedEvent",
    "BatchProgressEvent",
    "BatchCompleteEvent",
    "BatchProcessingCompleteEvent",
    "BatchResultsProcessedEvent",
    "BatchErrorEvent",
    "BatchPassthroughEvent",
    "BatchStatusEvent",
    "BatchSubmissionFailedEvent",
    "BatchStatusCheckFailedEvent",
    "BatchResultProcessingFailedEvent",
    "BatchPartialFailureEvent",
]


@dataclass
class BatchSubmittedEvent(BaseEvent):
    """Fired when a batch is submitted for processing."""

    batch_id: str = ""
    action_name: str = ""
    request_count: int = 0
    provider: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        self.message = (
            f"Batch {self.batch_id} submitted: {self.request_count} requests to {self.provider}"
        )
        self.data = {
            "batch_id": self.batch_id,
            "action_name": self.action_name,
            "request_count": self.request_count,
            "provider": self.provider,
        }

    @property
    def code(self) -> str:
        return "B001"


@dataclass
class BatchProgressEvent(BaseEvent):
    """Fired to report batch processing progress."""

    batch_id: str = ""
    completed: int = 0
    total: int = 0
    failed: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.BATCH
        pct = (self.completed / self.total * 100) if self.total > 0 else 0
        self.message = f"Batch {self.batch_id}: {self.completed}/{self.total} ({pct:.1f}%)"
        self.data = {
            "batch_id": self.batch_id,
            "completed": self.completed,
            "total": self.total,
            "failed": self.failed,
            "percentage": pct,
        }

    @property
    def code(self) -> str:
        return "B002"


@dataclass
class BatchCompleteEvent(BaseEvent):
    """Fired when a batch completes processing."""

    batch_id: str = ""
    action_name: str = ""
    total: int = 0
    completed: int = 0
    failed: int = 0
    elapsed_time: float = 0.0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        status = "OK" if self.failed == 0 else f"PARTIAL ({self.failed} failed)"
        self.message = f"Batch {self.batch_id} {status} in {self.elapsed_time:.2f}s"
        self.data = {
            "batch_id": self.batch_id,
            "action_name": self.action_name,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "elapsed_time": self.elapsed_time,
            "total_tokens": self.total_tokens,
        }

    @property
    def code(self) -> str:
        return "B003"


@dataclass
class BatchProcessingCompleteEvent(BaseEvent):
    """Fired when all batch jobs for an action are completed."""

    action_name: str = ""
    total_jobs: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        self.message = f"All batch jobs completed for {self.action_name}"
        self.data = {
            "action_name": self.action_name,
            "total_jobs": self.total_jobs,
        }

    @property
    def code(self) -> str:
        return "B004"


@dataclass
class BatchResultsProcessedEvent(BaseEvent):
    """Fired when batch results have been processed."""

    action_name: str = ""
    results_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        self.message = f"Processed all batch results for {self.action_name}"
        self.data = {
            "action_name": self.action_name,
            "results_count": self.results_count,
        }

    @property
    def code(self) -> str:
        return "B005"


@dataclass
class BatchErrorEvent(BaseEvent):
    """Fired when a batch processing error occurs."""

    action_name: str = ""
    error_message: str = ""
    error_type: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.BATCH
        self.message = f"Batch error for {self.action_name}: {self.error_message}"
        self.data = {
            "action_name": self.action_name,
            "error_message": self.error_message,
            "error_type": self.error_type,
        }

    @property
    def code(self) -> str:
        return "B006"


@dataclass
class BatchPassthroughEvent(BaseEvent):
    """Fired when all items were filtered and passthrough data was processed."""

    action_name: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.INFO
        self.category = EventCategories.BATCH
        self.message = f"All items filtered by conditional clause - passthrough data processed for {self.action_name}"
        self.data = {
            "action_name": self.action_name,
        }

    @property
    def code(self) -> str:
        return "B007"


@dataclass
class BatchStatusEvent(BaseEvent):
    """Fired to report batch status."""

    action_name: str = ""
    status_message: str = ""
    status_type: str = "info"  # info, warning, error

    def __post_init__(self) -> None:
        level_map = {
            "info": EventLevel.INFO,
            "warning": EventLevel.WARN,
            "error": EventLevel.ERROR,
        }
        self.level = level_map.get(self.status_type, EventLevel.INFO)
        self.category = EventCategories.BATCH
        self.message = self.status_message or f"Batch status for {self.action_name}"
        self.data = {
            "action_name": self.action_name,
            "status_message": self.status_message,
            "status_type": self.status_type,
        }

    @property
    def code(self) -> str:
        return "B008"


@dataclass
class BatchSubmissionFailedEvent(BaseEvent):
    """Fired when batch submission fails."""

    batch_id: str = ""
    provider: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.BATCH
        self.message = f"Batch submission failed ({self.provider}): {self.error}"
        self.data = {
            "batch_id": self.batch_id,
            "provider": self.provider,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "B009"


@dataclass
class BatchStatusCheckFailedEvent(BaseEvent):
    """Fired when batch status check fails."""

    batch_id: str = ""
    provider: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.BATCH
        self.message = f"Failed to check batch status for {self.batch_id}: {self.error}"
        self.data = {
            "batch_id": self.batch_id,
            "provider": self.provider,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "B010"


@dataclass
class BatchResultProcessingFailedEvent(BaseEvent):
    """Fired when batch result processing fails."""

    batch_id: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.BATCH
        self.message = f"Failed to process batch results for {self.batch_id}: {self.error}"
        self.data = {
            "batch_id": self.batch_id,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "B011"


@dataclass
class BatchPartialFailureEvent(BaseEvent):
    """Fired when some batch items fail."""

    batch_id: str = ""
    failed_count: int = 0
    total_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.BATCH
        self.message = f"Batch {self.batch_id} partial failure: {self.failed_count}/{self.total_count} items failed"
        self.data = {
            "batch_id": self.batch_id,
            "failed_count": self.failed_count,
            "total_count": self.total_count,
        }

    @property
    def code(self) -> str:
        return "B012"
