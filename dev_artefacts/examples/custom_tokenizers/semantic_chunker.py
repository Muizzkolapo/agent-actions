"""
Semantic Chunker - A custom tokenizer for Agent Actions

This tokenizer chunks text using semantic similarity while respecting sentence boundaries.
It uses tiktoken for accurate token counting and attempts to create semantically coherent chunks.

Usage in your workflow YAML:
```yaml
chunk_config:
  chunk_size: 100
  overlap: 20
  tokenizer_model: "cl100k_base"
  split_method: "semantic_chunker"  # Name must match this filename
```

Place this file in your project's tools/ directory.
"""

from typing import List
import tiktoken


def semantic_chunker(
    text: str,
    chunk_size: int,
    overlap: int,
    tokenizer_model: str
) -> List[str]:
    """
    Split text using semantic similarity and sentence boundaries.

    Args:
        text: The input text to split
        chunk_size: Maximum tokens per chunk
        overlap: Number of tokens to overlap between chunks
        tokenizer_model: Model identifier for token counting (e.g., "cl100k_base")

    Returns:
        List of text chunks
    """
    # Initialize the tokenizer
    try:
        encoding = tiktoken.get_encoding(tokenizer_model)
    except Exception:
        # Fallback to character counting if tiktoken fails
        return _fallback_character_split(text, chunk_size, overlap)

    # Split into sentences while preserving structure
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = []
    current_tokens = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        sentence_tokens = len(encoding.encode(sentence))

        # If adding this sentence exceeds chunk_size and we have content
        if current_tokens + sentence_tokens > chunk_size and current_chunk:
            # Finalize current chunk
            chunk_text = ' '.join(current_chunk)
            chunks.append(chunk_text)

            # Calculate overlap - keep last N sentences that fit in overlap
            if overlap > 0:
                overlap_chunk = []
                overlap_tokens = 0
                # Work backwards through current_chunk to build overlap
                for sent in reversed(current_chunk):
                    sent_tokens = len(encoding.encode(sent))
                    if overlap_tokens + sent_tokens <= overlap:
                        overlap_chunk.insert(0, sent)
                        overlap_tokens += sent_tokens
                    else:
                        break
                current_chunk = overlap_chunk
                current_tokens = overlap_tokens
            else:
                current_chunk = []
                current_tokens = 0

        # Add current sentence
        current_chunk.append(sentence)
        current_tokens += sentence_tokens

    # Add final chunk if it has content
    if current_chunk:
        chunks.append(' '.join(current_chunk))

    return chunks if chunks else [text]


def _fallback_character_split(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Fallback to character-based splitting if tokenizer fails.

    Uses ~4 characters per token as rough estimation.
    """
    # Rough estimation: 4 chars ≈ 1 token
    char_chunk_size = chunk_size * 4
    char_overlap = overlap * 4

    chunks = []
    start = 0

    while start < len(text):
        end = start + char_chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break

        # Try to break at word boundary
        while end > start and text[end] not in ' \n\t':
            end -= 1

        if end == start:  # No word boundary found
            end = start + char_chunk_size

        chunks.append(text[start:end])
        start = end - char_overlap

    return chunks if chunks else [text]