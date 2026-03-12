"""Centralized access to batch context metadata fields."""

from typing import Any, Dict, Optional

from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus


class BatchContextMetadata:
    """Static helpers for reading and writing internal metadata on batch context records."""

    # =========================================================================
    # Filter Status Methods
    # =========================================================================

    @staticmethod
    def set_filter_status(record: Dict[str, Any], status: FilterStatus) -> None:
        """Set the filter status on a record."""
        record[ContextMetaKeys.FILTER_STATUS] = str(status)

    @staticmethod
    def get_filter_status(record: Dict[str, Any]) -> Optional[FilterStatus]:
        """Get the filter status from a record, or None if unset/invalid."""
        status_str = record.get(ContextMetaKeys.FILTER_STATUS)
        if status_str is None:
            return None

        try:
            return FilterStatus(status_str)
        except ValueError:
            return None

    @staticmethod
    def is_included(record: Dict[str, Any]) -> bool:
        """Check if record has INCLUDED filter status."""
        return BatchContextMetadata.get_filter_status(record) == FilterStatus.INCLUDED

    @staticmethod
    def is_skipped(record: Dict[str, Any]) -> bool:
        """Check if record has SKIPPED filter status."""
        return BatchContextMetadata.get_filter_status(record) == FilterStatus.SKIPPED

    @staticmethod
    def is_filtered(record: Dict[str, Any]) -> bool:
        """Check if record has FILTERED filter status."""
        return BatchContextMetadata.get_filter_status(record) == FilterStatus.FILTERED

    # =========================================================================
    # Passthrough Fields Methods
    # =========================================================================

    @staticmethod
    def set_passthrough_fields(record: Dict[str, Any], fields: Dict[str, Any]) -> None:
        """Set passthrough fields on a record."""
        record[ContextMetaKeys.PASSTHROUGH_FIELDS] = fields

    @staticmethod
    def get_passthrough_fields(record: Dict[str, Any]) -> Dict[str, Any]:
        """Get passthrough fields from a record, or empty dict if unset."""
        return record.get(ContextMetaKeys.PASSTHROUGH_FIELDS, {})

    @staticmethod
    def pop_passthrough_fields(record: Dict[str, Any]) -> Dict[str, Any]:
        """Remove and return passthrough fields from a record."""
        return record.pop(ContextMetaKeys.PASSTHROUGH_FIELDS, {})

    # =========================================================================
    # Utility Methods
    # =========================================================================

    @staticmethod
    def strip_internal_fields(record: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of record with all internal metadata fields removed."""
        internal_keys = ContextMetaKeys.all_internal_keys()
        return {k: v for k, v in record.items() if k not in internal_keys}

    @staticmethod
    def has_internal_fields(record: Dict[str, Any]) -> bool:
        """Check if record contains any internal metadata fields."""
        internal_keys = ContextMetaKeys.all_internal_keys()
        return any(k in record for k in internal_keys)
