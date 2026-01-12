"""Core types for unified record processing architecture."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ProcessingStatus(Enum):
    """Status of record processing."""

    SUCCESS = "success"  # Processed successfully
    SKIPPED = "skipped"  # Skipped by guard (passthrough)
    FILTERED = "filtered"  # Filtered out by guard (excluded)
    FAILED = "failed"  # Processing failed
    EXHAUSTED = "exhausted"  # Retry exhausted


class ProcessingMode(Enum):
    """Processing mode for record handling."""

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
        attempts: Number of retry attempts made
        reason: Why retry was needed (timeout, api_error, missing, rate_limit)
    """

    attempts: int
    reason: str  # "timeout", "api_error", "missing", "rate_limit"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {"attempts": self.attempts, "reason": self.reason}


@dataclass
class RecoveryMetadata:
    """
    Container for all recovery-related metadata.

    Stored in output records under the _recovery key when recovery occurred.
    Only present if retry or reprompt was actually triggered.
    """

    retry: Optional[RetryMetadata] = None
    # reprompt: Optional[RepromptMetadata] = None  # Future: Phase 2

    def to_dict(self) -> Optional[Dict[str, Any]]:
        """Convert to dictionary for JSON serialization. Returns None if empty."""
        result: Dict[str, Any] = {}
        if self.retry:
            result["retry"] = self.retry.to_dict()
        # if self.reprompt:
        #     result["reprompt"] = self.reprompt.to_dict()
        return result if result else None

    def is_empty(self) -> bool:
        """Check if any recovery occurred."""
        return self.retry is None  # and self.reprompt is None


@dataclass
class ProcessingResult:
    """
    Unified result type replacing tuple/list returns.

    This replaces fragile tuple returns with a typed, extensible structure.
    Adding new fields requires only updating this dataclass and consumers.
    """

    status: ProcessingStatus
    data: List[Dict[str, Any]] = field(default_factory=list)

    # Identity
    source_guid: Optional[str] = None
    node_id: Optional[str] = None

    # For first-stage: preserve original input for source saving
    source_snapshot: Optional[Dict[str, Any]] = None

    # Execution state
    executed: bool = True
    skip_reason: Optional[str] = None

    # Passthrough
    passthrough_fields: Dict[str, Any] = field(default_factory=dict)

    # Error handling
    error: Optional[str] = None
    retry_state: RetryState = field(default_factory=RetryState)

    # Recovery metadata (populated when retry/reprompt occurred)
    recovery_metadata: Optional[RecoveryMetadata] = None

    # LLM response (for metadata extraction)
    raw_response: Optional[Any] = None

    @classmethod
    def success(cls, data: List[Dict], **kwargs) -> "ProcessingResult":
        """Factory for successful result."""
        return cls(status=ProcessingStatus.SUCCESS, data=data, executed=True, **kwargs)

    @classmethod
    def skipped(cls, passthrough_data: Any, reason: str, **kwargs) -> "ProcessingResult":
        """Factory for skipped (passthrough) result."""
        data_list = (
            [passthrough_data] if not isinstance(passthrough_data, list) else passthrough_data
        )
        return cls(
            status=ProcessingStatus.SKIPPED,
            data=data_list,
            executed=False,
            skip_reason=reason,
            **kwargs,
        )

    @classmethod
    def filtered(cls, **kwargs) -> "ProcessingResult":
        """Factory for filtered (excluded) result."""
        return cls(status=ProcessingStatus.FILTERED, data=[], executed=False, **kwargs)

    @classmethod
    def failed(cls, error: str, **kwargs) -> "ProcessingResult":
        """Factory for failed result."""
        return cls(status=ProcessingStatus.FAILED, data=[], executed=False, error=error, **kwargs)


@dataclass
class ProcessingContext:
    """
    Context object flowing through processing pipeline.

    This replaces threading individual values through 6+ function calls.
    All processing-related state is contained in this single object.
    """

    # Core configuration
    agent_config: Dict[str, Any]
    agent_name: str
    mode: ProcessingMode = ProcessingMode.ONLINE

    # Is this first-stage (raw input) or subsequent-stage (structured input)?
    is_first_stage: bool = False

    # Source data for lookups
    source_data: List[Dict[str, Any]] = field(default_factory=list)

    # File context
    file_path: Optional[str] = None
    output_directory: Optional[str] = None

    # Loop context for {loop.*} references
    loop_context: Optional[Dict[str, Any]] = None
    workflow_metadata: Optional[Dict[str, Any]] = None

    # Current record position (for loop correlation)
    record_index: int = 0

    @property
    def action_name(self) -> str:
        """Get action name from config or agent_name."""
        return self.agent_config.get("agent_type", self.agent_name)
