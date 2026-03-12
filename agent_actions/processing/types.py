"""Core types for unified record processing architecture."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

from agent_actions.config.types import AgentConfigDict

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


class ProcessingStatus(Enum):
    """Status of record processing."""

    SUCCESS = "success"  # Processed successfully
    SKIPPED = "skipped"  # Skipped by guard (passthrough)
    FILTERED = "filtered"  # Filtered out by guard (excluded)
    FAILED = "failed"  # Processing failed
    EXHAUSTED = "exhausted"  # Retry exhausted
    DEFERRED = "deferred"  # Deferred for batch execution
    UNPROCESSED = "unprocessed"  # Upstream failed/skipped this record


class ProcessingMode(Enum):
    """Workflow-level data flow mode: ONLINE (synchronous) or BATCH (queued)."""

    ONLINE = "online"
    BATCH = "batch"


@dataclass
class RetryState:
    """Retry-related state for a processing operation."""

    attempts: int = 0
    last_error: Optional[str] = None
    exhausted: bool = False


@dataclass
class RetryMetadata:
    """Metadata for retry recovery, stored in output _recovery.retry field."""

    attempts: int
    failures: int
    succeeded: bool
    reason: str  # "timeout", "api_error", "missing", "rate_limit", "network_error"
    timestamp: Optional[str] = None  # ISO format (e.g., "2024-01-13T12:30:45Z")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "attempts": self.attempts,
            "failures": self.failures,
            "succeeded": self.succeeded,
            "reason": self.reason,
        }
        if self.timestamp:
            result["timestamp"] = self.timestamp
        return result


@dataclass
class RepromptMetadata:
    """Metadata for reprompt recovery, stored in output _recovery.reprompt field."""

    attempts: int
    passed: bool
    validation: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "attempts": self.attempts,
            "passed": self.passed,
            "validation": self.validation,
        }


@dataclass
class RecoveryMetadata:
    """Container for recovery metadata, stored under the _recovery output key."""

    retry: Optional[RetryMetadata] = None
    reprompt: Optional[RepromptMetadata] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization. Returns empty dict if no recovery."""
        result: dict[str, Any] = {}
        if self.retry:
            result["retry"] = self.retry.to_dict()
        if self.reprompt:
            result["reprompt"] = self.reprompt.to_dict()
        return result

    def is_empty(self) -> bool:
        """Return True if no recovery occurred."""
        return self.retry is None and self.reprompt is None


@dataclass
class ProcessingResult:
    """Unified result type for record processing output."""

    status: ProcessingStatus
    data: list[dict[str, Any]] = field(default_factory=list)

    source_guid: Optional[str] = None
    node_id: Optional[str] = None
    source_snapshot: Optional[dict[str, Any]] = None
    input_record: Optional[dict[str, Any]] = None
    executed: bool = True
    skip_reason: Optional[str] = None
    passthrough_fields: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    retry_state: RetryState = field(default_factory=RetryState)
    recovery_metadata: Optional[RecoveryMetadata] = None
    raw_response: Optional[Any] = None
    pre_extracted_metadata: Optional[dict[str, Any]] = None

    @classmethod
    def success(
        cls,
        data: list[dict[str, Any]],
        *,
        source_guid: Optional[str] = None,
        passthrough_fields: Optional[dict[str, Any]] = None,
        source_snapshot: Optional[dict[str, Any]] = None,
        raw_response: Optional[Any] = None,
        recovery_metadata: Optional["RecoveryMetadata"] = None,
        input_record: Optional[dict[str, Any]] = None,
        pre_extracted_metadata: Optional[dict[str, Any]] = None,
    ) -> "ProcessingResult":
        """Factory for successful result."""
        return cls(
            status=ProcessingStatus.SUCCESS,
            data=data,
            executed=True,
            source_guid=source_guid,
            passthrough_fields=passthrough_fields or {},
            source_snapshot=source_snapshot,
            raw_response=raw_response,
            recovery_metadata=recovery_metadata,
            input_record=input_record,
            pre_extracted_metadata=pre_extracted_metadata,
        )

    @classmethod
    def skipped(
        cls,
        passthrough_data: Any,
        reason: str,
        *,
        source_guid: Optional[str] = None,
    ) -> "ProcessingResult":
        """Factory for skipped (passthrough) result."""
        if passthrough_data is None:
            data_list: list = []
        elif isinstance(passthrough_data, list):
            data_list = passthrough_data
        else:
            data_list = [passthrough_data]
        return cls(
            status=ProcessingStatus.SKIPPED,
            data=data_list,
            executed=False,
            skip_reason=reason,
            source_guid=source_guid,
        )

    @classmethod
    def filtered(
        cls,
        *,
        source_guid: Optional[str] = None,
        source_snapshot: Optional[dict[str, Any]] = None,
        input_record: Optional[dict[str, Any]] = None,
    ) -> "ProcessingResult":
        """Factory for filtered (excluded) result."""
        return cls(
            status=ProcessingStatus.FILTERED,
            data=[],
            executed=False,
            source_guid=source_guid,
            source_snapshot=source_snapshot,
            input_record=input_record,
        )

    @classmethod
    def failed(
        cls,
        error: str,
        *,
        source_guid: Optional[str] = None,
        source_snapshot: Optional[dict[str, Any]] = None,
        input_record: Optional[dict[str, Any]] = None,
    ) -> "ProcessingResult":
        """Factory for failed result."""
        return cls(
            status=ProcessingStatus.FAILED,
            data=[],
            executed=False,
            error=error,
            source_guid=source_guid,
            source_snapshot=source_snapshot,
            input_record=input_record,
        )

    @classmethod
    def exhausted(
        cls,
        error: str,
        *,
        data: Optional[list[dict[str, Any]]] = None,
        source_guid: Optional[str] = None,
        recovery_metadata: Optional["RecoveryMetadata"] = None,
        source_snapshot: Optional[dict[str, Any]] = None,
        input_record: Optional[dict[str, Any]] = None,
    ) -> "ProcessingResult":
        """Factory for exhausted (retry) result."""
        return cls(
            status=ProcessingStatus.EXHAUSTED,
            data=data or [],
            executed=False,
            error=error,
            source_guid=source_guid,
            recovery_metadata=recovery_metadata,
            source_snapshot=source_snapshot,
            input_record=input_record,
        )

    @classmethod
    def unprocessed(
        cls,
        data: list[dict[str, Any]],
        reason: str,
        *,
        source_guid: Optional[str] = None,
        source_snapshot: Optional[dict[str, Any]] = None,
        input_record: Optional[dict[str, Any]] = None,
    ) -> "ProcessingResult":
        """Factory for unprocessed (upstream dead/failed/skipped) result."""
        return cls(
            status=ProcessingStatus.UNPROCESSED,
            data=data,
            executed=False,
            skip_reason=reason,
            source_guid=source_guid,
            source_snapshot=source_snapshot,
            input_record=input_record,
        )

    @classmethod
    def deferred(
        cls,
        task_id: str,
        *,
        source_guid: Optional[str] = None,
        passthrough_fields: Optional[dict[str, Any]] = None,
        source_snapshot: Optional[dict[str, Any]] = None,
        input_record: Optional[dict[str, Any]] = None,
    ) -> "ProcessingResult":
        """Factory for deferred (batch) result."""
        return cls(
            status=ProcessingStatus.DEFERRED,
            data=[],
            executed=False,
            node_id=task_id,
            source_guid=source_guid,
            passthrough_fields=passthrough_fields or {},
            source_snapshot=source_snapshot,
            input_record=input_record,
        )

    @property
    def task_id(self) -> Optional[str]:
        """Batch task ID (only meaningful when status is DEFERRED)."""
        return self.node_id if self.status == ProcessingStatus.DEFERRED else None


@dataclass
class ProcessingContext:
    """Context object flowing through the processing pipeline."""

    agent_config: AgentConfigDict
    agent_name: str
    mode: ProcessingMode = ProcessingMode.ONLINE
    is_first_stage: bool = False
    source_data: list[dict[str, Any]] = field(default_factory=list)
    file_path: Optional[str] = None
    output_directory: Optional[str] = None
    version_context: Optional[dict[str, Any]] = None
    workflow_metadata: Optional[dict[str, Any]] = None
    record_index: int = 0
    agent_indices: Optional[dict[str, int]] = None
    dependency_configs: Optional[dict[str, Any]] = None
    current_item: Optional[dict[str, Any]] = None
    storage_backend: Optional["StorageBackend"] = None

    @property
    def action_name(self) -> str:
        """Get action name from config or agent_name."""
        return self.agent_config.get("agent_type", self.agent_name)
