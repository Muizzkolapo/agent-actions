"""Chunking strategies for field-level text processing."""

from abc import ABC, abstractmethod
from typing import List
from agent_actions.preprocessing.transformation.string_transformer import Tokenizer


class ChunkingStrategy(ABC):
    """Abstract base class for text chunking strategies."""

    @abstractmethod
    def split_text_into_chunks(
        self, text_content: str, maximum_chunk_size: int, overlap_size: int
    ) -> List[str]:
        """
        Split text content into smaller chunks according to the strategy.

        Args:
            text_content: The complete text content to split into chunks
            maximum_chunk_size: Maximum allowed size for each individual chunk
            overlap_size: Number of tokens/characters to overlap between consecutive chunks

        Returns:
            List of text chunks with applied overlap
        """
        pass


class TiktokenChunkingStrategy(ChunkingStrategy):
    """Token-based chunking strategy using tiktoken tokenizer."""

    def __init__(self, tokenizer_model_name: str = 'cl100k_base'):
        """
        Initialize tiktoken-based chunking strategy.

        Args:
            tokenizer_model_name: The tiktoken model name to use for tokenization
        """
        self.tokenizer_model_name = tokenizer_model_name

    def split_text_into_chunks(
        self, text_content: str, maximum_chunk_size: int, overlap_size: int
    ) -> List[str]:
        """
        Split text into chunks based on token count using tiktoken tokenizer.

        Args:
            text_content: The complete text content to split
            maximum_chunk_size: Maximum number of tokens allowed per chunk
            overlap_size: Number of tokens to overlap between consecutive chunks

        Returns:
            List of text chunks with token-based boundaries
        """
        if not text_content:
            return ['']

        return Tokenizer.split_text_content(
            text_content,
            maximum_chunk_size,
            overlap_size,
            tokenizer_model=self.tokenizer_model_name,
            split_method='tiktoken'
        )


class CharBasedChunkingStrategy(ChunkingStrategy):
    """Character-based chunking strategy that splits on character boundaries."""

    def split_text_into_chunks(
        self, text_content: str, maximum_chunk_size: int, overlap_size: int
    ) -> List[str]:
        """
        Split text into chunks based on character count.

        Args:
            text_content: The complete text content to split
            maximum_chunk_size: Maximum number of characters allowed per chunk
            overlap_size: Number of characters to overlap between consecutive chunks

        Returns:
            List of text chunks with character-based boundaries
        """
        if not text_content:
            return ['']

        return Tokenizer.split_text_content(
            text_content,
            maximum_chunk_size,
            overlap_size,
            split_method='chars'
        )


class SpacyChunkingStrategy(ChunkingStrategy):
    """Semantic chunking strategy using spaCy sentence boundaries."""

    def split_text_into_chunks(
        self, text_content: str, maximum_chunk_size: int, overlap_size: int
    ) -> List[str]:
        """
        Split text into chunks based on spaCy sentence boundaries.

        Args:
            text_content: The complete text content to split
            maximum_chunk_size: Target chunk size in tokens
            overlap_size: Number of tokens to overlap between consecutive chunks

        Returns:
            List of text chunks with semantic sentence boundaries
        """
        if not text_content:
            return ['']

        return Tokenizer.split_text_content(
            text_content,
            maximum_chunk_size,
            overlap_size,
            split_method='spacy'
        )
