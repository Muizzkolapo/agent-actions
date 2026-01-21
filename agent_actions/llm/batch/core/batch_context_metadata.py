"""
Centralized access to batch context metadata fields.
"""

from typing import Any, Dict, Optional

from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus


class BatchContextMetadata:
    """Helper class for batch context metadata operations.

    Provides static methods for accessing and modifying internal metadata
    fields on batch context records. All methods are class-level to enable
    usage without instantiation.

    Example:
        >>> record = {"id": "test", "content": "data"}
        >>> BatchContextMetadata.set_filter_status(record, FilterStatus.INCLUDED)
        >>> BatchContextMetadata.is_included(record)
        True
        >>> clean = BatchContextMetadata.strip_internal_fields(record)
        >>> "_batch_filter_status" in clean
        False
    """

    # =========================================================================
    # Filter Status Methods
    # =========================================================================

    @staticmethod
    def set_filter_status(record: Dict[str, Any], status: FilterStatus) -> None:
        """Set the filter status on a record.

        Args:
            record: The record dict to modify
            status: FilterStatus enum value to set
        """
        record[ContextMetaKeys.FILTER_STATUS] = str(status)

    @staticmethod
    def get_filter_status(record: Dict[str, Any]) -> Optional[FilterStatus]:
        """Get the filter status from a record.

        Args:
            record: The record dict to read from

        Returns:
            FilterStatus enum value if set and valid, None otherwise
        """
        status_str = record.get(ContextMetaKeys.FILTER_STATUS)
        if status_str is None:
            return None

        try:
            return FilterStatus(status_str)
        except ValueError:
            return None

    @staticmethod
    def is_included(record: Dict[str, Any]) -> bool:
        """Check if record has included status.

        Args:
            record: The record dict to check

        Returns:
            True if filter status is INCLUDED, False otherwise
        """
        return BatchContextMetadata.get_filter_status(record) == FilterStatus.INCLUDED

    @staticmethod
    def is_skipped(record: Dict[str, Any]) -> bool:
        """Check if record has skipped status.

        Args:
            record: The record dict to check

        Returns:
            True if filter status is SKIPPED, False otherwise
        """
        return BatchContextMetadata.get_filter_status(record) == FilterStatus.SKIPPED

    @staticmethod
    def is_filtered(record: Dict[str, Any]) -> bool:
        """Check if record has filtered status.

        Args:
            record: The record dict to check

        Returns:
            True if filter status is FILTERED, False otherwise
        """
        return BatchContextMetadata.get_filter_status(record) == FilterStatus.FILTERED

    # =========================================================================
    # Passthrough Fields Methods
    # =========================================================================

    @staticmethod
    def set_passthrough_fields(record: Dict[str, Any], fields: Dict[str, Any]) -> None:
        """Set passthrough fields on a record.

        Args:
            record: The record dict to modify
            fields: Dictionary of fields to pass through
        """
        record[ContextMetaKeys.PASSTHROUGH_FIELDS] = fields

    @staticmethod
    def get_passthrough_fields(record: Dict[str, Any]) -> Dict[str, Any]:
        """Get passthrough fields from a record.

        Args:
            record: The record dict to read from

        Returns:
            Dictionary of passthrough fields, or empty dict if not set
        """
        return record.get(ContextMetaKeys.PASSTHROUGH_FIELDS, {})

    @staticmethod
    def pop_passthrough_fields(record: Dict[str, Any]) -> Dict[str, Any]:
        """Remove and return passthrough fields from a record.

        Args:
            record: The record dict to modify

        Returns:
            Dictionary of passthrough fields that were removed, or empty dict
        """
        return record.pop(ContextMetaKeys.PASSTHROUGH_FIELDS, {})

    # =========================================================================
    # Utility Methods
    # =========================================================================

    @staticmethod
    def strip_internal_fields(record: Dict[str, Any]) -> Dict[str, Any]:
        """Create a copy of record with all internal metadata fields removed.

        Args:
            record: The record dict to copy and clean

        Returns:
            New dict with internal fields removed
        """
        internal_keys = ContextMetaKeys.all_internal_keys()
        return {k: v for k, v in record.items() if k not in internal_keys}

    @staticmethod
    def has_internal_fields(record: Dict[str, Any]) -> bool:
        """Check if record contains any internal metadata fields.

        Args:
            record: The record dict to check

        Returns:
            True if any internal fields are present, False otherwise
        """
        internal_keys = ContextMetaKeys.all_internal_keys()
        return any(k in record for k in internal_keys)
