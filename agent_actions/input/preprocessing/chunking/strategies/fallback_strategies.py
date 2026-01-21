"""Fallback strategies for handling edge cases in field chunking."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Dict, Any, Tuple

if TYPE_CHECKING:
    from agent_actions.input.preprocessing.chunking.field_chunking import FieldChunkingError
else:

    class FieldChunkingError(Exception):
        """Raised when field chunking operations fail."""


class FallbackStrategy(ABC):
    """Abstract base class for fallback strategies."""

    @abstractmethod
    def handle_oversized_field(
        self, field_value: str, field_name: str, maximum_field_size: int
    ) -> Tuple[str, str]:
        """
        Handle field value that exceeds maximum size limit.

        Args:
            field_value: The field value to potentially truncate or modify
            field_name: Name of the field being processed
            maximum_field_size: Maximum allowed field size in characters

        Returns:
            Tuple of (processed_field_value, fallback_operation_message)
        """

    @abstractmethod
    def handle_excessive_chunk_count(
        self, chunk_list: List[str], field_name: str, maximum_chunks_allowed: int
    ) -> Tuple[List[str], str]:
        """
        Handle field that generates more chunks than allowed limit.

        Args:
            chunk_list: List of text chunks generated from field
            field_name: Name of the field being processed
            maximum_chunks_allowed: Maximum number of chunks permitted per field

        Returns:
            Tuple of (processed_chunk_list, fallback_operation_message)
        """

    @abstractmethod
    def handle_chunking_error(
        self, record: Dict[str, Any], field_name: str, error_message: str
    ) -> List[Dict[str, Any]]:
        """
        Handle errors that occur during field chunking process.

        Args:
            record: The complete record being processed when error occurred
            field_name: Name of the field that triggered the error
            error_message: Detailed error message describing what went wrong

        Returns:
            List of processed record chunks (may be empty, single record, or multiple)
        """


class PreserveOriginalStrategy(FallbackStrategy):
    """Fallback strategy that preserves original content in all cases."""

    def handle_oversized_field(
        self, field_value: str, field_name: str, maximum_field_size: int
    ) -> Tuple[str, str]:
        """Preserve the full original field value without any modification."""
        operation_message = f"preserved_oversized_field_{field_name}"
        return field_value, operation_message

    def handle_excessive_chunk_count(
        self, chunk_list: List[str], field_name: str, maximum_chunks_allowed: int
    ) -> Tuple[List[str], str]:
        """Preserve all chunks even if they exceed the maximum allowed count."""
        operation_message = f"preserved_excessive_chunk_count_for_{field_name}"
        return chunk_list, operation_message

    def handle_chunking_error(
        self, record: Dict[str, Any], field_name: str, error_message: str
    ) -> List[Dict[str, Any]]:
        """Preserve the original record with error metadata attached."""
        preserved_record = record.copy()
        preserved_record["chunk_info"] = {
            "source_field": field_name,
            "chunk_index": 1,
            "total_chunks": 1,
            "chunking_error": error_message,
            "fallback_applied": "preserve_original_on_error",
        }
        return [preserved_record]


class TruncateStrategy(FallbackStrategy):
    """Fallback strategy that truncates content to fit within specified limits."""

    def handle_oversized_field(
        self, field_value: str, field_name: str, maximum_field_size: int
    ) -> Tuple[str, str]:
        """Truncate field value to the specified maximum size limit."""
        truncated_value = field_value[:maximum_field_size]
        operation_message = f"truncated_{field_name}_at_position_{maximum_field_size}"
        return truncated_value, operation_message

    def handle_excessive_chunk_count(
        self, chunk_list: List[str], field_name: str, maximum_chunks_allowed: int
    ) -> Tuple[List[str], str]:
        """Limit chunk list to maximum allowed count by truncating excess chunks."""
        truncated_chunk_list = chunk_list[:maximum_chunks_allowed]
        operation_message = f"limited_chunk_count_for_{field_name}_to_{maximum_chunks_allowed}"
        return truncated_chunk_list, operation_message

    def handle_chunking_error(
        self, record: Dict[str, Any], field_name: str, error_message: str
    ) -> List[Dict[str, Any]]:
        """Skip the record entirely when chunking error occurs."""
        return []


class SkipStrategy(FallbackStrategy):
    """Fallback strategy that skips problematic content entirely."""

    def handle_oversized_field(
        self, field_value: str, field_name: str, maximum_field_size: int
    ) -> Tuple[str, str]:
        """Skip oversized field by returning empty string."""
        empty_field_value = ""
        operation_message = f"skipped_oversized_field_{field_name}"
        return empty_field_value, operation_message

    def handle_excessive_chunk_count(
        self, chunk_list: List[str], field_name: str, maximum_chunks_allowed: int
    ) -> Tuple[List[str], str]:
        """Skip field with excessive chunks by returning empty list."""
        empty_chunk_list = []
        operation_message = f"skipped_excessive_chunk_count_for_{field_name}"
        return empty_chunk_list, operation_message

    def handle_chunking_error(
        self, record: Dict[str, Any], field_name: str, error_message: str
    ) -> List[Dict[str, Any]]:
        """Skip the record entirely when chunking error occurs."""
        return []


class ErrorStrategy(FallbackStrategy):
    """Fallback strategy that raises errors instead of handling issues gracefully."""

    def handle_oversized_field(
        self, field_value: str, field_name: str, maximum_field_size: int
    ) -> Tuple[str, str]:
        """Raise exception when field exceeds maximum allowed size."""
        raise FieldChunkingError(
            f"Field '{field_name}' exceeds maximum allowed size of {maximum_field_size} characters"
        )

    def handle_excessive_chunk_count(
        self, chunk_list: List[str], field_name: str, maximum_chunks_allowed: int
    ) -> Tuple[List[str], str]:
        """Raise exception when chunk count exceeds maximum allowed limit."""
        actual_chunk_count = len(chunk_list)
        raise FieldChunkingError(
            f"Field '{field_name}' generated {actual_chunk_count} chunks, "
            f"exceeding maximum allowed limit of {maximum_chunks_allowed}"
        )

    def handle_chunking_error(
        self, record: Dict[str, Any], field_name: str, error_message: str
    ) -> List[Dict[str, Any]]:
        """Re-raise chunking error with detailed context information."""
        raise FieldChunkingError(f"Failed to chunk field '{field_name}': {error_message}")
