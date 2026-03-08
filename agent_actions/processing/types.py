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
    """Workflow-level data flow mode for record handling.

    ONLINE/BATCH controls whether LLM calls are synchronous or queued.
    Not to be confused with ``config.interfaces.ProcessingMode``
    (SYNC/ASYNC/AUTO) which controls CLI-level execution mode.
    """

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
    """
    Metadata for retry recovery, stored in output _recovery.retry field.

    Attributes:
        attempts: Total number of attempts made (failures + 1 if succeeded)
        failures: Number of failed attempts before success (or total if exhausted)
        succeeded: Whether the operation ultimately succeeded
        reason: Why retry was needed (timeout, api_error, missing, rate_limit, network_error)
        timestamp: ISO format timestamp when retry completed
    """

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
    """
    Metadata for reprompt recovery, stored in output _recovery.reprompt field.

    Attributes:
        attempts: Number of reprompt attempts made
        passed: Whether validation ultimately passed
        validation: Name of the validation UDF that was used
    """

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
    """
    Container for all recovery-related metadata.

    Stored in output records under the _recovery key when recovery occurred.
    Only present if retry or reprompt was actually triggered.
    """

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
        """Check if any recovery occurred."""
        return self.retry is None and self.reprompt is None


@dataclass
class ProcessingResult:
    """
    Unified result type replacing tuple/list returns.

    This replaces fragile tuple returns with a typed, extensible structure.
    Adding new fields requires only updating this dataclass and consumers.
    """

    status: ProcessingStatus
    data: list[dict[str, Any]] = field(default_factory=list)

    # Identity
    source_guid: Optional[str] = None
    node_id: Optional[str] = None

    # For first-stage: preserve original input for source saving
    source_snapshot: Optional[dict[str, Any]] = None

    # For downstream: preserve full input record (with lineage, target_id, etc.)
    input_record: Optional[dict[str, Any]] = None

    # Execution state
    executed: bool = True
    skip_reason: Optional[str] = None

    # Passthrough
    passthrough_fields: dict[str, Any] = field(default_factory=dict)

    # Error handling
    error: Optional[str] = None
    retry_state: RetryState = field(default_factory=RetryState)

    # Recovery metadata (populated when retry/reprompt occurred)
    recovery_metadata: Optional[RecoveryMetadata] = None

    # LLM response (for metadata extraction)
    raw_response: Optional[Any] = None

    # Pre-extracted metadata (batch path provides this directly)
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
        """Factory for deferred (batch) result.

        Args:
            task_id: Unique identifier for retrieving result later
        """
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
    """
    Context object flowing through processing pipeline.

    This replaces threading individual values through 6+ function calls.
    All processing-related state is contained in this single object.
    """

    # Core configuration
    agent_config: AgentConfigDict
    agent_name: str
    mode: ProcessingMode = ProcessingMode.ONLINE

    # Is this first-stage (raw input) or subsequent-stage (structured input)?
    is_first_stage: bool = False

    # Source data for lookups
    source_data: list[dict[str, Any]] = field(default_factory=list)

    # File context
    file_path: Optional[str] = None
    output_directory: Optional[str] = None

    # Version context for {version.*} references
    version_context: Optional[dict[str, Any]] = None
    workflow_metadata: Optional[dict[str, Any]] = None

    # Current record position (for loop correlation)
    record_index: int = 0

    # Workflow context for historical data loading
    agent_indices: Optional[dict[str, int]] = None
    dependency_configs: Optional[dict[str, Any]] = None

    # Current item (per-record) for lineage chaining in realtime processing
    current_item: Optional[dict[str, Any]] = None

    # Storage backend for database-backed persistence and historical data loading
    storage_backend: Optional["StorageBackend"] = None

    @property
    def action_name(self) -> str:
        """Get action name from config or agent_name."""
        return self.agent_config.get("agent_type", self.agent_name)
