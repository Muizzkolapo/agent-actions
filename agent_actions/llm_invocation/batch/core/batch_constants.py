"""Constants for batch processing module.

This module centralizes all constant values used across the batch module,
eliminating magic strings and providing type-safe enums for status tracking.
"""

from enum import Enum
from typing import Set


class BatchStatus(str, Enum):
    """Batch job status values.

    Inherits from str to enable direct string comparison and JSON serialization.

    Example:
        >>> status = BatchStatus.COMPLETED
        >>> status == "completed"  # True
        >>> status.is_terminal()   # True
    """

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
    def terminal_states(cls) -> Set["BatchStatus"]:
        """Get set of terminal (final) batch states.

        Returns:
            Set of BatchStatus values that indicate a batch has finished.
        """
        return {cls.COMPLETED, cls.FAILED, cls.CANCELLED}

    @classmethod
    def in_flight_states(cls) -> Set["BatchStatus"]:
        """Get set of in-flight (active) batch states.

        Returns:
            Set of BatchStatus values that indicate a batch is still processing.
        """
        return {cls.SUBMITTED, cls.VALIDATING, cls.IN_PROGRESS, cls.FINALIZING}

    def is_terminal(self) -> bool:
        """Check if this status is a terminal state.

        Returns:
            True if batch has finished (completed, failed, or cancelled).
        """
        return self in self.terminal_states()

    def is_in_flight(self) -> bool:
        """Check if this status is an in-flight state.

        Returns:
            True if batch is still processing.
        """
        return self in self.in_flight_states()


class FilterStatus(str, Enum):
    """Record filter status values.

    Used to track which records were included, skipped, or filtered
    during batch task preparation.

    Example:
        >>> status = FilterStatus.INCLUDED
        >>> status == "included"  # True
    """

    INCLUDED = "included"
    SKIPPED = "skipped"
    FILTERED = "filtered"

    def __str__(self) -> str:
        """Return the string value for str() conversion."""
        return self.value


class ContextMetaKeys:
    """Internal metadata keys used in context maps.

    These keys are used to track internal state during batch processing.
    All keys start with underscore to indicate they are internal metadata
    and should not be included in final output.

    Example:
        >>> row = {"content": "data", ContextMetaKeys.FILTER_STATUS: "included"}
        >>> row.get(ContextMetaKeys.FILTER_STATUS)
        'included'
    """

    FILTER_STATUS = "_batch_filter_status"
    PASSTHROUGH_FIELDS = "_passthrough_fields"
    RETRY_METADATA = "_retry_metadata"

    @classmethod
    def all_internal_keys(cls) -> Set[str]:
        """Get set of all internal metadata keys.

        Returns:
            Set of all internal key names used in context maps.
        """
        return {cls.FILTER_STATUS, cls.PASSTHROUGH_FIELDS, cls.RETRY_METADATA}
