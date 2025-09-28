"""
Test script for the semantic_chunker custom tokenizer.

Run this to verify your custom tokenizer works before using it in Agent Actions.

Usage:
    python test_semantic_chunker.py
"""

from semantic_chunker import semantic_chunker


def test_basic_chunking():
    """Test basic sentence chunking."""
    text = """
    This is the first sentence. This is the second sentence. This is the third sentence.
    This is the fourth sentence. This is the fifth sentence. This is the sixth sentence.
    This is the seventh sentence. This is the eighth sentence.
    """

    chunks = semantic_chunker(
        text=text.strip(),
        chunk_size=50,
        overlap=10,
        tokenizer_model="cl100k_base"
    )

    print("=" * 60)
    print("TEST 1: Basic Chunking")
    print("=" * 60)
    print(f"Original text length: {len(text)} characters")
    print(f"Number of chunks: {len(chunks)}\n")

    for i, chunk in enumerate(chunks, 1):
        print(f"Chunk {i}:")
        print(f"  Length: {len(chunk)} chars")
        print(f"  Content: {chunk[:100]}...")
        print()


def test_with_paragraphs():
    """Test chunking with paragraph structure."""
    text = """
    The quick brown fox jumps over the lazy dog. This sentence demonstrates basic English vocabulary.
    It contains several common words used in typing practice.

    Agent Actions is a powerful framework for building multi-agent workflows. It provides tools for
    text processing, tokenization, and field-level chunking. The framework supports multiple LLM vendors
    including OpenAI, Anthropic, and others.

    Custom tokenizers allow you to implement specialized text splitting logic. You can use sentence
    boundaries, semantic similarity, or any other criteria that makes sense for your use case.
    """

    chunks = semantic_chunker(
        text=text.strip(),
        chunk_size=80,
        overlap=15,
        tokenizer_model="cl100k_base"
    )

    print("=" * 60)
    print("TEST 2: Paragraph Chunking")
    print("=" * 60)
    print(f"Original text length: {len(text)} characters")
    print(f"Number of chunks: {len(chunks)}\n")

    for i, chunk in enumerate(chunks, 1):
        print(f"Chunk {i}:")
        print(f"  {chunk}")
        print()


def test_edge_cases():
    """Test edge cases."""
    print("=" * 60)
    print("TEST 3: Edge Cases")
    print("=" * 60)

    # Empty text
    result = semantic_chunker("", 100, 20, "cl100k_base")
    print(f"Empty text: {len(result)} chunks - {result}")

    # Very short text
    result = semantic_chunker("Short.", 100, 20, "cl100k_base")
    print(f"Short text: {len(result)} chunks - {result}")

    # Single long sentence
    long_sentence = "This is a very long sentence that contains many words and should definitely exceed the chunk size limit that we have set for this particular test case to ensure proper handling of oversized content."
    result = semantic_chunker(long_sentence, 20, 5, "cl100k_base")
    print(f"Long sentence: {len(result)} chunks")
    for i, chunk in enumerate(result, 1):
        print(f"  Chunk {i}: {chunk[:50]}...")
    print()


if __name__ == "__main__":
    print("\n🧪 Testing Semantic Chunker\n")

    try:
        test_basic_chunking()
        test_with_paragraphs()
        test_edge_cases()

        print("=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        print("\nYour tokenizer is ready to use in Agent Actions!")
        print("Place semantic_chunker.py in your project's tools/ directory.")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()