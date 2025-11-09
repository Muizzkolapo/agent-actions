"""Chunking strategies for field-level text processing."""

from abc import ABC, abstractmethod
from typing import List
from agent_actions.preprocessing.string_transformer import Tokenizer


class ChunkingStrategy(ABC):
    """Abstract base class for text chunking strategies."""

    @abstractmethod
    def chunk(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """
        Chunk text according to the strategy.

        Args:
            text: The text to chunk
            chunk_size: Maximum size of each chunk
            overlap: Number of tokens/characters to overlap between chunks

        Returns:
            List of text chunks
        """
        pass


class TiktokenChunkingStrategy(ChunkingStrategy):
    """Token-based chunking strategy using tiktoken tokenizer."""

    def __init__(self, tokenizer_model: str = 'cl100k_base'):
        """
        Initialize tiktoken chunking strategy.

        Args:
            tokenizer_model: The tiktoken model to use for tokenization
        """
        self.tokenizer_model = tokenizer_model

    def chunk(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """
        Chunk text based on token count using tiktoken.

        Args:
            text: The text to chunk
            chunk_size: Maximum number of tokens per chunk
            overlap: Number of tokens to overlap between chunks

        Returns:
            List of text chunks
        """
        if not text:
            return ['']

        return Tokenizer.split_text_content(
            text,
            chunk_size,
            overlap,
            tokenizer_model=self.tokenizer_model,
            split_method='tiktoken'
        )


class CharBasedChunkingStrategy(ChunkingStrategy):
    """Character-based chunking strategy."""

    def chunk(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """
        Chunk text based on character count.

        Args:
            text: The text to chunk
            chunk_size: Maximum number of characters per chunk
            overlap: Number of characters to overlap between chunks

        Returns:
            List of text chunks
        """
        if not text:
            return ['']

        return Tokenizer.split_text_content(
            text,
            chunk_size,
            overlap,
            split_method='chars'
        )


class SpacyChunkingStrategy(ChunkingStrategy):
    """Spacy-based semantic chunking strategy."""

    def chunk(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """
        Chunk text based on spacy sentence boundaries.

        Args:
            text: The text to chunk
            chunk_size: Target chunk size (in tokens)
            overlap: Number of tokens to overlap between chunks

        Returns:
            List of text chunks
        """
        if not text:
            return ['']

        return Tokenizer.split_text_content(
            text,
            chunk_size,
            overlap,
            split_method='spacy'
        )
