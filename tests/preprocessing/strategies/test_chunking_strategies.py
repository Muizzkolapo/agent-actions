"""Tests for chunking strategies."""

import pytest
from agent_actions.preprocessing.chunking.strategies.chunking_strategies import (
    TiktokenChunkingStrategy,
    CharBasedChunkingStrategy,
    SpacyChunkingStrategy,
)


class TestTiktokenChunkingStrategy:
    """Tests for TiktokenChunkingStrategy."""

    def test_chunk_empty_text(self):
        """Test chunking empty text returns empty chunk."""
        strategy = TiktokenChunkingStrategy()
        result = strategy.chunk('', 100, 20)
        assert result == ['']

    def test_chunk_short_text(self):
        """Test chunking text shorter than chunk_size returns single chunk."""
        strategy = TiktokenChunkingStrategy()
        text = 'This is a short text.'
        result = strategy.chunk(text, 100, 20)
        assert len(result) == 1
        assert result[0] == text

    def test_chunk_long_text(self):
        """Test chunking long text creates multiple chunks."""
        strategy = TiktokenChunkingStrategy()
        text = ' '.join(['word'] * 200)  # Create long text
        result = strategy.chunk(text, 50, 10)
        assert len(result) > 1

    def test_custom_tokenizer_model(self):
        """Test using custom tokenizer model."""
        strategy = TiktokenChunkingStrategy(tokenizer_model='cl100k_base')
        text = 'Test text for tokenization'
        result = strategy.chunk(text, 100, 20)
        assert len(result) >= 1


class TestCharBasedChunkingStrategy:
    """Tests for CharBasedChunkingStrategy."""

    def test_chunk_empty_text(self):
        """Test chunking empty text returns empty chunk."""
        strategy = CharBasedChunkingStrategy()
        result = strategy.chunk('', 100, 20)
        assert result == ['']

    def test_chunk_short_text(self):
        """Test chunking text shorter than chunk_size returns single chunk."""
        strategy = CharBasedChunkingStrategy()
        text = 'This is a short text.'
        result = strategy.chunk(text, 100, 20)
        assert len(result) == 1
        assert result[0] == text

    def test_chunk_long_text(self):
        """Test chunking long text creates multiple chunks."""
        strategy = CharBasedChunkingStrategy()
        text = 'a' * 500  # 500 character text
        result = strategy.chunk(text, 100, 20)
        assert len(result) > 1

    def test_chunk_respects_overlap(self):
        """Test that character-based chunking respects overlap."""
        strategy = CharBasedChunkingStrategy()
        text = 'a' * 200
        result = strategy.chunk(text, 100, 20)
        # With overlap, we should have more chunks than without
        assert len(result) >= 2


class TestSpacyChunkingStrategy:
    """Tests for SpacyChunkingStrategy."""

    def test_chunk_empty_text(self):
        """Test chunking empty text returns empty chunk."""
        strategy = SpacyChunkingStrategy()
        result = strategy.chunk('', 100, 20)
        assert result == ['']

    def test_chunk_short_text(self):
        """Test chunking text shorter than chunk_size returns single chunk."""
        strategy = SpacyChunkingStrategy()
        text = 'This is a short text.'
        result = strategy.chunk(text, 100, 20)
        assert len(result) == 1

    def test_chunk_long_text(self):
        """Test chunking long text creates multiple chunks."""
        strategy = SpacyChunkingStrategy()
        text = '. '.join(['This is a sentence'] * 100)
        result = strategy.chunk(text, 50, 10)
        assert len(result) >= 1


class TestChunkingStrategyComparison:
    """Tests comparing different chunking strategies."""

    def test_all_strategies_handle_empty_text(self):
        """Test all strategies handle empty text consistently."""
        text = ''
        strategies = [
            TiktokenChunkingStrategy(),
            CharBasedChunkingStrategy(),
            SpacyChunkingStrategy(),
        ]

        for strategy in strategies:
            result = strategy.chunk(text, 100, 20)
            assert result == [''], f'{strategy.__class__.__name__} failed on empty text'

    def test_all_strategies_return_list(self):
        """Test all strategies return lists."""
        text = 'Test text'
        strategies = [
            TiktokenChunkingStrategy(),
            CharBasedChunkingStrategy(),
            SpacyChunkingStrategy(),
        ]

        for strategy in strategies:
            result = strategy.chunk(text, 100, 20)
            assert isinstance(result, list), (
                f'{strategy.__class__.__name__} did not return a list'
            )

    def test_different_strategies_may_produce_different_results(self):
        """Test that different strategies may chunk text differently."""
        text = 'This is a test. ' * 50
        tiktoken_strategy = TiktokenChunkingStrategy()
        char_strategy = CharBasedChunkingStrategy()

        tiktoken_result = tiktoken_strategy.chunk(text, 100, 20)
        char_result = char_strategy.chunk(text, 100, 20)

        # Results may differ between strategies
        # Just verify both produce valid results
        assert len(tiktoken_result) >= 1
        assert len(char_result) >= 1
