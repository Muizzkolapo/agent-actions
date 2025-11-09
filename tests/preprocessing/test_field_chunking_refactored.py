"""Integration tests for refactored field chunking module."""

import pytest
from agent_actions.preprocessing.field_chunking import (
    FieldAnalyzer,
    FieldChunker,
    FieldAnalysisResult,
    FieldChunkingValidationError,
    FieldChunkingError,
)


class TestFieldAnalyzerRefactored:
    """Integration tests for refactored FieldAnalyzer."""

    def test_analyzer_basic_configuration(self):
        """Test analyzer with basic configuration."""
        config = {
            'chunk_size': 1000,
            'overlap': 200,
            'tokenizer_model': 'cl100k_base',
            'field_chunking': {
                'enabled': True,
                'chunk_fields': ['content'],
                'chunk_threshold': 100,
            },
        }

        analyzer = FieldAnalyzer(config)
        assert analyzer.chunk_fields == ['content']
        assert analyzer.chunk_threshold == 100

    def test_analyzer_detects_fields_to_chunk(self):
        """Test that analyzer correctly identifies fields needing chunking."""
        config = {
            'tokenizer_model': 'cl100k_base',
            'field_chunking': {
                'enabled': True,
                'chunk_fields': ['content'],
                'chunk_threshold': 10,
            },
        }

        analyzer = FieldAnalyzer(config)
        record = {
            'id': '123',
            'content': 'This is a long piece of content that needs to be chunked.',
            'title': 'Short title',
        }

        result = analyzer.analyze_record(record)

        assert isinstance(result, FieldAnalysisResult)
        assert 'content' in result.fields_to_chunk
        assert result.requires_chunking

    def test_analyzer_respects_preserve_fields(self):
        """Test that analyzer doesn't chunk preserved fields."""
        config = {
            'tokenizer_model': 'cl100k_base',
            'field_chunking': {
                'enabled': True,
                'chunk_fields': ['content', 'description'],
                'preserve_fields': ['description'],
                'chunk_threshold': 0,
            },
        }

        with pytest.raises(FieldChunkingValidationError) as exc_info:
            FieldAnalyzer(config)

        assert 'cannot be both chunked and preserved' in str(exc_info.value)

    def test_analyzer_with_auto_detection(self):
        """Test analyzer with auto-detection enabled."""
        config = {
            'tokenizer_model': 'cl100k_base',
            'field_chunking': {
                'enabled': True,
                'auto_detection': {'enabled': True},
                'chunk_threshold': 5,  # Lower threshold to ensure content exceeds it
            },
        }

        analyzer = FieldAnalyzer(config)
        record = {
            'id': '123',
            'content': 'This is long content with many words for testing and chunking.',
            'description': 'Another long description field with more words.',
            'title': 'Short',
        }

        result = analyzer.analyze_record(record)

        # Should detect all string fields except those below threshold
        assert result.requires_chunking


class TestFieldChunkerRefactored:
    """Integration tests for refactored FieldChunker."""

    def test_chunker_basic_configuration(self):
        """Test chunker initialization with basic configuration."""
        config = {
            'chunk_size': 1000,
            'overlap': 200,
            'tokenizer_model': 'cl100k_base',
            'split_method': 'tiktoken',
            'field_chunking': {
                'enabled': True,
                'fallback_strategy': 'preserve_original',
                'max_chunks_per_record': 100,
                'truncate_at': 50000,
            },
        }

        chunker = FieldChunker(config)
        assert chunker.chunk_size == 1000
        assert chunker.overlap == 200
        assert chunker.max_chunks_per_record == 100

    def test_chunker_chunks_single_field(self):
        """Test chunking a single field."""
        config = {
            'chunk_size': 50,
            'overlap': 10,
            'tokenizer_model': 'cl100k_base',
            'split_method': 'chars',
            'field_chunking': {
                'enabled': True,
                'fallback_strategy': 'preserve_original',
            },
        }

        chunker = FieldChunker(config)
        analysis = FieldAnalysisResult(
            fields_to_chunk=['content'], field_sizes={'content': 200}
        )

        record = {'id': '123', 'content': 'a' * 200, 'title': 'Test'}

        chunks = chunker.chunk_record(record, analysis)

        assert len(chunks) > 1  # Should create multiple chunks
        assert all('chunk_info' in chunk for chunk in chunks)
        assert all(chunk['title'] == 'Test' for chunk in chunks)  # Preserve non-chunked fields

    def test_chunker_with_truncate_strategy(self):
        """Test chunker with truncate fallback strategy."""
        config = {
            'chunk_size': 1000,
            'overlap': 200,
            'field_chunking': {
                'enabled': True,
                'fallback_strategy': 'truncate',
                'truncate_at': 100,
                'max_chunks_per_record': 2,
            },
        }

        chunker = FieldChunker(config)
        analysis = FieldAnalysisResult(
            fields_to_chunk=['content'], field_sizes={'content': 500}
        )

        record = {'id': '123', 'content': 'a' * 500}

        chunks = chunker.chunk_record(record, analysis)

        # Should be truncated due to truncate_at limit
        assert len(chunks) >= 1
        for chunk in chunks:
            assert 'fallback_applied' in chunk['chunk_info']

    def test_chunker_with_error_strategy(self):
        """Test chunker with error fallback strategy on excessive chunks."""
        config = {
            'chunk_size': 10,
            'overlap': 0,
            'split_method': 'chars',
            'field_chunking': {
                'enabled': True,
                'fallback_strategy': 'error',
                'max_chunks_per_record': 2,
            },
        }

        chunker = FieldChunker(config)
        analysis = FieldAnalysisResult(
            fields_to_chunk=['content'], field_sizes={'content': 100}
        )

        record = {'id': '123', 'content': 'a' * 100}

        # Should raise error due to excessive chunks
        with pytest.raises(FieldChunkingError):
            chunker.chunk_record(record, analysis)

    def test_chunker_with_enhanced_metadata(self):
        """Test chunker with enhanced metadata strategy."""
        config = {
            'chunk_size': 50,
            'overlap': 10,
            'tokenizer_model': 'cl100k_base',
            'split_method': 'chars',
            'field_chunking': {
                'enabled': True,
                'chunk_metadata': {
                    'add_chunk_info': True,
                    'chunk_id_field': 'chunk_id',
                    'original_record_id': 'parent_id',
                    'add_char_positions': True,
                    'add_token_counts': True,
                },
            },
        }

        chunker = FieldChunker(config)
        analysis = FieldAnalysisResult(
            fields_to_chunk=['content'], field_sizes={'content': 200}
        )

        record = {'id': '123', 'content': 'a' * 200}

        chunks = chunker.chunk_record(record, analysis)

        assert len(chunks) > 0
        for chunk in chunks:
            assert 'chunk_id' in chunk  # Should be at record level
            assert 'parent_id' in chunk  # Should be at record level
            assert 'chunk_info' in chunk
            assert 'chunk_start_char' in chunk['chunk_info']
            assert 'chunk_size_tokens' in chunk['chunk_info']


class TestBackwardCompatibility:
    """Tests to ensure backward compatibility with existing API."""

    def test_field_analyzer_public_api(self):
        """Test that FieldAnalyzer public API remains unchanged."""
        config = {
            'tokenizer_model': 'cl100k_base',
            'field_chunking': {
                'enabled': True,
                'chunk_fields': ['content'],
                'chunk_threshold': 10,
            },
        }

        analyzer = FieldAnalyzer(config)

        # Public methods should still work
        record = {'id': '1', 'content': 'test content'}
        result = analyzer.analyze_record(record)
        assert isinstance(result, FieldAnalysisResult)

        # should_chunk_field should work
        should_chunk = analyzer.should_chunk_field('content', 100)
        assert isinstance(should_chunk, bool)

        # detect_text_fields should work
        text_fields = analyzer.detect_text_fields(record)
        assert isinstance(text_fields, list)

    def test_field_chunker_public_api(self):
        """Test that FieldChunker public API remains unchanged."""
        config = {
            'chunk_size': 1000,
            'overlap': 200,
            'field_chunking': {'enabled': True},
        }

        chunker = FieldChunker(config)

        # chunk_field should work
        chunks = chunker.chunk_field('test content', 'content')
        assert isinstance(chunks, list)

        # chunk_record should work
        analysis = FieldAnalysisResult(fields_to_chunk=['content'])
        record = {'content': 'test'}
        result = chunker.chunk_record(record, analysis)
        assert isinstance(result, list)

    def test_integration_with_staging_content_pattern(self):
        """Test the integration pattern used by staging_content.py."""
        # This mimics how staging_content.py uses field chunking
        chunk_config = {
            'chunk_size': 1000,
            'overlap': 200,
            'tokenizer_model': 'cl100k_base',
            'field_chunking': {
                'enabled': True,
                'chunk_fields': ['page_content'],
                'chunk_threshold': 500,
            },
        }

        # Create analyzer and chunker
        analyzer = FieldAnalyzer(chunk_config)
        chunker = FieldChunker(chunk_config)

        # Process a record
        record = {
            'id': '123',
            'page_content': 'This is a long page content. ' * 100,
            'url': 'https://example.com',
        }

        # Analyze
        analysis = analyzer.analyze_record(record)

        # Chunk if needed
        if analysis.requires_chunking:
            chunked_records = chunker.chunk_record(record, analysis)
            assert len(chunked_records) > 0
            assert all('chunk_info' in r for r in chunked_records)
        else:
            chunked_records = [record]

        assert len(chunked_records) >= 1


class TestValidationErrors:
    """Tests for configuration validation."""

    def test_invalid_chunk_size(self):
        """Test that invalid chunk_size raises error."""
        config = {
            'chunk_size': -100,  # Invalid
            'field_chunking': {'enabled': True, 'chunk_fields': ['content']},
        }

        with pytest.raises(FieldChunkingValidationError) as exc_info:
            FieldChunker(config)

        assert 'chunk_size must be positive' in str(exc_info.value)

    def test_invalid_overlap(self):
        """Test that invalid overlap raises error."""
        config = {
            'chunk_size': 100,
            'overlap': 150,  # Overlap larger than chunk_size
            'field_chunking': {'enabled': True, 'chunk_fields': ['content']},
        }

        with pytest.raises(FieldChunkingValidationError) as exc_info:
            FieldChunker(config)

        assert 'overlap must be smaller than chunk_size' in str(exc_info.value)

    def test_invalid_field_rules(self):
        """Test that invalid field rules raise error."""
        config = {
            'chunk_size': 1000,
            'field_chunking': {
                'enabled': True,
                'chunk_fields': ['content'],
                'field_rules': {
                    'content': {
                        'chunk_size': -50,  # Invalid
                    }
                },
            },
        }

        with pytest.raises(FieldChunkingValidationError) as exc_info:
            FieldAnalyzer(config)

        assert 'chunk_size must be positive' in str(exc_info.value)
