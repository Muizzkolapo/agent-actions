"""Metadata creation strategies for chunk information."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any
from agent_actions.preprocessing.string_transformer import Tokenizer


@dataclass
class MetadataContext:
    """Context information for metadata creation."""

    record: Dict[str, Any]
    field_name: str
    field_value: str
    chunk: str
    chunk_index: int
    total_chunks: int


class MetadataStrategy(ABC):
    """Abstract base class for chunk metadata creation."""

    @abstractmethod
    def create_metadata(self, context: MetadataContext) -> Dict[str, Any]:
        """
        Create metadata for a chunk.

        Args:
            context: MetadataContext containing all information needed for metadata creation

        Returns:
            Dictionary of metadata fields
        """
        pass


class BasicMetadataStrategy(MetadataStrategy):
    """Basic metadata strategy that creates minimal chunk information."""

    def create_metadata(self, context: MetadataContext) -> Dict[str, Any]:
        """
        Create basic metadata with only essential chunk information.

        Args:
            context: MetadataContext with chunk details

        Returns:
            Dictionary with source_field, chunk_index, and total_chunks
        """
        return {
            'source_field': context.field_name,
            'chunk_index': context.chunk_index,
            'total_chunks': context.total_chunks,
        }


class EnhancedMetadataStrategy(MetadataStrategy):
    """Enhanced metadata strategy with configurable additional fields."""

    def __init__(self, config: Dict[str, Any], tokenizer_model: str):
        """
        Initialize enhanced metadata strategy.

        Args:
            config: Metadata configuration dictionary from chunk_metadata
            tokenizer_model: Tokenizer model to use for token counting
        """
        self.config = config
        self.tokenizer_model = tokenizer_model

    def create_metadata(self, context: MetadataContext) -> Dict[str, Any]:
        """
        Create enhanced metadata with configurable additional fields.

        Args:
            context: MetadataContext with chunk details

        Returns:
            Dictionary with basic metadata plus any configured enhancements
        """
        metadata = {
            'source_field': context.field_name,
            'chunk_index': context.chunk_index,
            'total_chunks': context.total_chunks,
        }

        # Add chunk ID if configured
        if self.config.get('chunk_id_field'):
            chunk_id = self._create_chunk_id(context)
            metadata[self.config['chunk_id_field']] = chunk_id

        # Add original record ID if configured
        if self.config.get('original_record_id'):
            original_id = context.record.get('id')
            if original_id:
                metadata[self.config['original_record_id']] = original_id

        # Add character positions if configured
        if self.config.get('add_char_positions', False):
            metadata.update(self._add_char_positions(context))

        # Add token counts if configured
        if self.config.get('add_token_counts', False):
            metadata.update(self._add_token_counts(context))

        return metadata

    def _create_chunk_id(self, context: MetadataContext) -> str:
        """
        Create a unique chunk ID.

        Args:
            context: MetadataContext with chunk details

        Returns:
            Unique chunk identifier string
        """
        original_id = context.record.get('id', 'unknown')
        return f'{original_id}_{context.field_name}_{context.chunk_index}'

    def _add_char_positions(self, context: MetadataContext) -> Dict[str, Any]:
        """
        Add character position metadata.

        Args:
            context: MetadataContext with chunk details

        Returns:
            Dictionary with character position metadata
        """
        chunk_size_chars = len(context.chunk)
        estimated_start = (context.chunk_index - 1) * chunk_size_chars
        return {
            'chunk_start_char': max(0, estimated_start),
            'chunk_end_char': estimated_start + chunk_size_chars,
            'chunk_size_chars': chunk_size_chars,
            'original_field_size_chars': len(context.field_value),
        }

    def _add_token_counts(self, context: MetadataContext) -> Dict[str, Any]:
        """
        Add token count metadata.

        Args:
            context: MetadataContext with chunk details

        Returns:
            Dictionary with token count metadata
        """
        chunk_tokens = Tokenizer.num_tokens_from_string(
            context.chunk, self.tokenizer_model
        )
        original_tokens = Tokenizer.num_tokens_from_string(
            context.field_value, self.tokenizer_model
        )
        return {
            'chunk_size_tokens': chunk_tokens,
            'original_field_size_tokens': original_tokens,
        }
