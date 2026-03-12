"""Constants for batch processing: status enums and metadata keys."""

from enum import Enum


class BatchStatus(str, Enum):
    """Batch job status values (inherits str for JSON serialization)."""

    SUBMITTED = "submitted"
    VALIDATING = "validating"
    IN_PROGRESS = "in_progress"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        """Return the string value for str() conversion."""
        return self.value

    @classmethod
    def terminal_states(cls) -> set["BatchStatus"]:
        """Return the set of terminal (final) batch states."""
        return {cls.COMPLETED, cls.FAILED, cls.CANCELLED}

    @classmethod
    def in_flight_states(cls) -> set["BatchStatus"]:
        """Return the set of in-flight (active) batch states."""
        return {cls.SUBMITTED, cls.VALIDATING, cls.IN_PROGRESS, cls.FINALIZING}

    def is_terminal(self) -> bool:
        """Check if this status is a terminal state."""
        return self in self.terminal_states()

    def is_in_flight(self) -> bool:
        """Check if this status is an in-flight state."""
        return self in self.in_flight_states()


class FilterStatus(str, Enum):
    """Record filter status during batch task preparation."""

    INCLUDED = "included"
    SKIPPED = "skipped"
    FILTERED = "filtered"

    def __str__(self) -> str:
        """Return the string value for str() conversion."""
        return self.value


class ContextMetaKeys:
    """Internal underscore-prefixed metadata keys used in batch context maps."""

    FILTER_STATUS = "_batch_filter_status"
    FILTER_PHASE = "_batch_filter_phase"  # "phase1" or "phase2" - which phase filtered
    PASSTHROUGH_FIELDS = "_passthrough_fields"

    @classmethod
    def all_internal_keys(cls) -> set[str]:
        """Return set of all internal metadata key names."""
        return {cls.FILTER_STATUS, cls.FILTER_PHASE, cls.PASSTHROUGH_FIELDS}
