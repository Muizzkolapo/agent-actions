"""Metadata creation strategies for chunk information."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent_actions.input.preprocessing.transformation.string_transformer import Tokenizer


@dataclass
class MetadataContext:
    """Context information for metadata creation."""

    record: dict[str, Any]
    field_name: str
    field_value: str
    chunk: str
    chunk_index: int
    total_chunks: int


class MetadataStrategy(ABC):
    """Abstract base class for chunk metadata creation."""

    def __repr__(self):
        """Return string representation of MetadataStrategy."""
        return f"{self.__class__.__name__}()"

    @abstractmethod
    def create_metadata(self, context: MetadataContext) -> dict[str, Any]:
        """Create metadata for a chunk."""


class BasicMetadataStrategy(MetadataStrategy):
    """Basic metadata strategy that creates minimal chunk information."""

    def __repr__(self):
        """Return string representation of BasicMetadataStrategy."""
        return "BasicMetadataStrategy()"

    def create_metadata(self, context: MetadataContext) -> dict[str, Any]:
        """Create basic metadata with source_field, chunk_index, and total_chunks."""
        return {
            "source_field": context.field_name,
            "chunk_index": context.chunk_index,
            "total_chunks": context.total_chunks,
        }


class EnhancedMetadataStrategy(MetadataStrategy):
    """Enhanced metadata strategy with configurable additional fields."""

    def __init__(self, config: dict[str, Any], tokenizer_model: str):
        """Initialize enhanced metadata strategy."""
        self.config = config
        self.tokenizer_model = tokenizer_model

    def __repr__(self):
        """Return string representation of EnhancedMetadataStrategy."""
        return f"EnhancedMetadataStrategy(tokenizer_model={self.tokenizer_model!r})"

    def create_metadata(self, context: MetadataContext) -> dict[str, Any]:
        """Create enhanced metadata with configurable additional fields."""
        metadata = {
            "source_field": context.field_name,
            "chunk_index": context.chunk_index,
            "total_chunks": context.total_chunks,
        }

        if self.config.get("chunk_id_field"):
            chunk_id = self._create_chunk_id(context)
            metadata[self.config["chunk_id_field"]] = chunk_id

        if self.config.get("original_record_id"):
            original_id = context.record.get("id")
            if original_id:
                metadata[self.config["original_record_id"]] = original_id

        if self.config.get("add_char_positions", False):
            metadata.update(self._calculate_character_positions(context))

        if self.config.get("add_token_counts", False):
            metadata.update(self._calculate_token_counts(context))

        return metadata

    def _create_chunk_id(self, context: MetadataContext) -> str:
        """Create a unique chunk ID."""
        original_id = context.record.get("id", "unknown")
        return f"{original_id}_{context.field_name}_{context.chunk_index}"

    def _calculate_character_positions(self, context: MetadataContext) -> dict[str, Any]:
        """Calculate and return character position metadata for the chunk."""
        chunk_size_in_characters = len(context.chunk)
        estimated_start_position = (context.chunk_index - 1) * chunk_size_in_characters
        estimated_end_position = estimated_start_position + chunk_size_in_characters

        return {
            "chunk_start_char": max(0, estimated_start_position),
            "chunk_end_char": estimated_end_position,
            "chunk_size_chars": chunk_size_in_characters,
            "original_field_size_chars": len(context.field_value),
        }

    def _calculate_token_counts(self, context: MetadataContext) -> dict[str, Any]:
        """Calculate and return token count metadata for the chunk."""
        chunk_token_count = Tokenizer.num_tokens_from_string(context.chunk, self.tokenizer_model)
        original_field_token_count = Tokenizer.num_tokens_from_string(
            context.field_value, self.tokenizer_model
        )

        return {
            "chunk_size_tokens": chunk_token_count,
            "original_field_size_tokens": original_field_token_count,
        }
