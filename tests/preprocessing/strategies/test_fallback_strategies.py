"""Tests for fallback strategies."""

import pytest
from agent_actions.preprocessing.strategies.fallback_strategies import (
    PreserveOriginalStrategy,
    TruncateStrategy,
    SkipStrategy,
    ErrorStrategy,
)
from agent_actions.preprocessing.field_chunking import FieldChunkingError


class TestPreserveOriginalStrategy:
    """Tests for PreserveOriginalStrategy."""

    def test_apply_truncation_preserves_full_value(self):
        """Test that truncation preserves the full original value."""
        strategy = PreserveOriginalStrategy()
        field_value = 'a' * 10000
        result_value, msg = strategy.apply_truncation(field_value, 'test_field', 5000)

        assert result_value == field_value
        assert 'preserved_large_test_field' in msg

    def test_apply_excessive_chunks_preserves_all(self):
        """Test that excessive chunks are all preserved."""
        strategy = PreserveOriginalStrategy()
        chunks = ['chunk1', 'chunk2', 'chunk3', 'chunk4', 'chunk5']
        result_chunks, msg = strategy.apply_excessive_chunks(chunks, 'test_field', 3)

        assert result_chunks == chunks
        assert len(result_chunks) == 5
        assert 'preserved_excessive_chunks_test_field' in msg

    def test_handle_error_preserves_record(self):
        """Test that errors result in preserving the record with error info."""
        strategy = PreserveOriginalStrategy()
        record = {'id': '123', 'content': 'test content'}
        result = strategy.handle_error(record, 'content', 'Test error message')

        assert len(result) == 1
        assert result[0]['id'] == '123'
        assert 'chunk_info' in result[0]
        assert result[0]['chunk_info']['chunking_error'] == 'Test error message'
        assert result[0]['chunk_info']['fallback_applied'] == 'preserve_original_on_error'


class TestTruncateStrategy:
    """Tests for TruncateStrategy."""

    def test_apply_truncation_truncates_value(self):
        """Test that truncation truncates the value to the specified limit."""
        strategy = TruncateStrategy()
        field_value = 'a' * 10000
        result_value, msg = strategy.apply_truncation(field_value, 'test_field', 5000)

        assert len(result_value) == 5000
        assert result_value == 'a' * 5000
        assert 'truncated_test_field_at_5000' in msg

    def test_apply_excessive_chunks_limits_chunks(self):
        """Test that excessive chunks are limited to max_chunks."""
        strategy = TruncateStrategy()
        chunks = ['chunk1', 'chunk2', 'chunk3', 'chunk4', 'chunk5']
        result_chunks, msg = strategy.apply_excessive_chunks(chunks, 'test_field', 3)

        assert len(result_chunks) == 3
        assert result_chunks == ['chunk1', 'chunk2', 'chunk3']
        assert 'limited_chunks_test_field_to_3' in msg

    def test_handle_error_returns_empty(self):
        """Test that errors result in empty list (skip record)."""
        strategy = TruncateStrategy()
        record = {'id': '123', 'content': 'test content'}
        result = strategy.handle_error(record, 'content', 'Test error message')

        assert result == []


class TestSkipStrategy:
    """Tests for SkipStrategy."""

    def test_apply_truncation_returns_empty_string(self):
        """Test that truncation returns empty string."""
        strategy = SkipStrategy()
        field_value = 'a' * 10000
        result_value, msg = strategy.apply_truncation(field_value, 'test_field', 5000)

        assert result_value == ''
        assert 'skipped_large_test_field' in msg

    def test_apply_excessive_chunks_returns_empty_list(self):
        """Test that excessive chunks return empty list."""
        strategy = SkipStrategy()
        chunks = ['chunk1', 'chunk2', 'chunk3', 'chunk4', 'chunk5']
        result_chunks, msg = strategy.apply_excessive_chunks(chunks, 'test_field', 3)

        assert result_chunks == []
        assert 'skipped_excessive_chunks_test_field' in msg

    def test_handle_error_returns_empty(self):
        """Test that errors result in empty list."""
        strategy = SkipStrategy()
        record = {'id': '123', 'content': 'test content'}
        result = strategy.handle_error(record, 'content', 'Test error message')

        assert result == []


class TestErrorStrategy:
    """Tests for ErrorStrategy."""

    def test_apply_truncation_raises_error(self):
        """Test that truncation raises an error."""
        strategy = ErrorStrategy()
        field_value = 'a' * 10000

        with pytest.raises(FieldChunkingError) as exc_info:
            strategy.apply_truncation(field_value, 'test_field', 5000)

        assert 'test_field' in str(exc_info.value)
        assert 'exceeds truncate_at limit' in str(exc_info.value)

    def test_apply_excessive_chunks_raises_error(self):
        """Test that excessive chunks raise an error."""
        strategy = ErrorStrategy()
        chunks = ['chunk1', 'chunk2', 'chunk3', 'chunk4', 'chunk5']

        with pytest.raises(FieldChunkingError) as exc_info:
            strategy.apply_excessive_chunks(chunks, 'test_field', 3)

        assert 'test_field' in str(exc_info.value)
        assert 'generated 5 chunks' in str(exc_info.value)
        assert 'exceeding max of 3' in str(exc_info.value)

    def test_handle_error_raises_error(self):
        """Test that errors are re-raised."""
        strategy = ErrorStrategy()
        record = {'id': '123', 'content': 'test content'}

        with pytest.raises(FieldChunkingError) as exc_info:
            strategy.handle_error(record, 'content', 'Original error message')

        assert 'Failed to chunk field' in str(exc_info.value)
        assert 'content' in str(exc_info.value)
        assert 'Original error message' in str(exc_info.value)


class TestFallbackStrategyComparison:
    """Tests comparing different fallback strategies."""

    def test_all_strategies_return_expected_types(self):
        """Test all strategies return expected types."""
        strategies = [
            PreserveOriginalStrategy(),
            TruncateStrategy(),
            SkipStrategy(),
        ]

        for strategy in strategies:
            # Test truncation return type
            value, msg = strategy.apply_truncation('test', 'field', 100)
            assert isinstance(value, str)
            assert isinstance(msg, str)

            # Test excessive chunks return type
            chunks, msg = strategy.apply_excessive_chunks(['a', 'b'], 'field', 10)
            assert isinstance(chunks, list)
            assert isinstance(msg, str)

            # Test error handling return type
            result = strategy.handle_error({'id': '1'}, 'field', 'error')
            assert isinstance(result, list)

    def test_strategies_behave_differently(self):
        """Test that different strategies produce different behaviors."""
        field_value = 'a' * 1000
        preserve_strategy = PreserveOriginalStrategy()
        truncate_strategy = TruncateStrategy()
        skip_strategy = SkipStrategy()

        preserve_result, _ = preserve_strategy.apply_truncation(field_value, 'field', 500)
        truncate_result, _ = truncate_strategy.apply_truncation(field_value, 'field', 500)
        skip_result, _ = skip_strategy.apply_truncation(field_value, 'field', 500)

        # Preserve keeps original
        assert len(preserve_result) == 1000

        # Truncate limits to 500
        assert len(truncate_result) == 500

        # Skip returns empty
        assert skip_result == ''
