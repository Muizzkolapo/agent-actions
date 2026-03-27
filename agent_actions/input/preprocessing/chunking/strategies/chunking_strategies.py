"""Chunking strategies for field-level text processing."""

from abc import ABC, abstractmethod

from agent_actions.input.preprocessing.transformation.string_transformer import Tokenizer


class ChunkingStrategy(ABC):
    """Abstract base class for text chunking strategies."""

    def __repr__(self):
        """Return string representation of ChunkingStrategy."""
        return f"{self.__class__.__name__}()"

    @abstractmethod
    def split_text_into_chunks(
        self, text_content: str, maximum_chunk_size: int, overlap_size: int
    ) -> list[str]:
        """Split text content into smaller chunks according to the strategy."""


class TiktokenChunkingStrategy(ChunkingStrategy):
    """Token-based chunking strategy using tiktoken tokenizer."""

    def __init__(self, tokenizer_model_name: str = "cl100k_base"):
        """Initialize tiktoken-based chunking strategy."""
        self.tokenizer_model_name = tokenizer_model_name

    def __repr__(self):
        """Return string representation of TiktokenChunkingStrategy."""
        return f"TiktokenChunkingStrategy(tokenizer_model_name={self.tokenizer_model_name!r})"

    def split_text_into_chunks(
        self, text_content: str, maximum_chunk_size: int, overlap_size: int
    ) -> list[str]:
        """Split text into chunks based on token count using tiktoken tokenizer."""
        if not text_content:
            return [""]

        return Tokenizer.split_text_content(
            text_content,
            maximum_chunk_size,
            overlap_size,
            tokenizer_model=self.tokenizer_model_name,
            split_method="tiktoken",
        )


class CharBasedChunkingStrategy(ChunkingStrategy):
    """Character-based chunking strategy that splits on character boundaries."""

    def __repr__(self):
        """Return string representation of CharBasedChunkingStrategy."""
        return "CharBasedChunkingStrategy()"

    def split_text_into_chunks(
        self, text_content: str, maximum_chunk_size: int, overlap_size: int
    ) -> list[str]:
        """Split text into chunks based on character count."""
        if not text_content:
            return [""]

        return Tokenizer.split_text_content(
            text_content, maximum_chunk_size, overlap_size, split_method="chars"
        )


class SpacyChunkingStrategy(ChunkingStrategy):
    """Semantic chunking strategy using spaCy sentence boundaries."""

    def __repr__(self):
        """Return string representation of SpacyChunkingStrategy."""
        return "SpacyChunkingStrategy()"

    def split_text_into_chunks(
        self, text_content: str, maximum_chunk_size: int, overlap_size: int
    ) -> list[str]:
        """Split text into chunks based on spaCy sentence boundaries."""
        if not text_content:
            return [""]

        return Tokenizer.split_text_content(
            text_content, maximum_chunk_size, overlap_size, split_method="spacy"
        )
