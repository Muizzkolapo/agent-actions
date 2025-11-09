"""Fallback strategies for handling edge cases in field chunking."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple


class FallbackStrategy(ABC):
    """Abstract base class for fallback strategies."""

    @abstractmethod
    def apply_truncation(
        self, field_value: str, field_name: str, truncate_at: int
    ) -> Tuple[str, str]:
        """
        Apply truncation fallback for overly large fields.

        Args:
            field_value: The field value to potentially truncate
            field_name: Name of the field being processed
            truncate_at: Maximum allowed field size

        Returns:
            Tuple of (processed_value, fallback_message)
        """
        pass

    @abstractmethod
    def apply_excessive_chunks(
        self, chunks: List[str], field_name: str, max_chunks: int
    ) -> Tuple[List[str], str]:
        """
        Apply fallback for fields that generate too many chunks.

        Args:
            chunks: List of chunks generated from field
            field_name: Name of the field being processed
            max_chunks: Maximum allowed chunks per field

        Returns:
            Tuple of (processed_chunks, fallback_message)
        """
        pass

    @abstractmethod
    def handle_error(
        self, record: Dict[str, Any], field_name: str, error_msg: str
    ) -> List[Dict[str, Any]]:
        """
        Handle chunking errors based on fallback strategy.

        Args:
            record: The record being processed
            field_name: Name of the field that caused the error
            error_msg: Error message describing what went wrong

        Returns:
            List of record chunks (may be empty, single record, or multiple)
        """
        pass


class PreserveOriginalStrategy(FallbackStrategy):
    """Fallback strategy that preserves original content in all cases."""

    def apply_truncation(
        self, field_value: str, field_name: str, truncate_at: int
    ) -> Tuple[str, str]:
        """Preserve the full original field value without truncation."""
        return field_value, f'preserved_large_{field_name}'

    def apply_excessive_chunks(
        self, chunks: List[str], field_name: str, max_chunks: int
    ) -> Tuple[List[str], str]:
        """Preserve all chunks even if they exceed the maximum."""
        return chunks, f'preserved_excessive_chunks_{field_name}'

    def handle_error(
        self, record: Dict[str, Any], field_name: str, error_msg: str
    ) -> List[Dict[str, Any]]:
        """Preserve the original record with error metadata."""
        error_record = record.copy()
        error_record['chunk_info'] = {
            'source_field': field_name,
            'chunk_index': 1,
            'total_chunks': 1,
            'chunking_error': error_msg,
            'fallback_applied': 'preserve_original_on_error',
        }
        return [error_record]


class TruncateStrategy(FallbackStrategy):
    """Fallback strategy that truncates content to fit limits."""

    def apply_truncation(
        self, field_value: str, field_name: str, truncate_at: int
    ) -> Tuple[str, str]:
        """Truncate field value to the specified limit."""
        return field_value[:truncate_at], f'truncated_{field_name}_at_{truncate_at}'

    def apply_excessive_chunks(
        self, chunks: List[str], field_name: str, max_chunks: int
    ) -> Tuple[List[str], str]:
        """Truncate chunks list to maximum allowed chunks."""
        return (
            chunks[:max_chunks],
            f'limited_chunks_{field_name}_to_{max_chunks}',
        )

    def handle_error(
        self, record: Dict[str, Any], field_name: str, error_msg: str
    ) -> List[Dict[str, Any]]:
        """Return empty list on error (skip the record)."""
        return []


class SkipStrategy(FallbackStrategy):
    """Fallback strategy that skips problematic content."""

    def apply_truncation(
        self, field_value: str, field_name: str, truncate_at: int
    ) -> Tuple[str, str]:
        """Return empty string for overly large fields."""
        return '', f'skipped_large_{field_name}'

    def apply_excessive_chunks(
        self, chunks: List[str], field_name: str, max_chunks: int
    ) -> Tuple[List[str], str]:
        """Return empty list for excessive chunks."""
        return [], f'skipped_excessive_chunks_{field_name}'

    def handle_error(
        self, record: Dict[str, Any], field_name: str, error_msg: str
    ) -> List[Dict[str, Any]]:
        """Return empty list on error (skip the record)."""
        return []


class ErrorStrategy(FallbackStrategy):
    """Fallback strategy that raises errors instead of handling gracefully."""

    def apply_truncation(
        self, field_value: str, field_name: str, truncate_at: int
    ) -> Tuple[str, str]:
        """Raise error for overly large fields."""
        from agent_actions.preprocessing.field_chunking import FieldChunkingError

        raise FieldChunkingError(
            f"Field '{field_name}' exceeds truncate_at limit of {truncate_at}"
        )

    def apply_excessive_chunks(
        self, chunks: List[str], field_name: str, max_chunks: int
    ) -> Tuple[List[str], str]:
        """Raise error for excessive chunks."""
        from agent_actions.preprocessing.field_chunking import FieldChunkingError

        raise FieldChunkingError(
            f"Field '{field_name}' generated {len(chunks)} chunks, exceeding max of {max_chunks}"
        )

    def handle_error(
        self, record: Dict[str, Any], field_name: str, error_msg: str
    ) -> List[Dict[str, Any]]:
        """Re-raise the error."""
        from agent_actions.preprocessing.field_chunking import FieldChunkingError

        raise FieldChunkingError(f"Failed to chunk field '{field_name}': {error_msg}")
