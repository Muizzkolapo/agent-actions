"""Tests for metadata strategies."""

import pytest
from agent_actions.preprocessing.strategies.metadata_strategies import (
    BasicMetadataStrategy,
    EnhancedMetadataStrategy,
    MetadataContext,
)


class TestBasicMetadataStrategy:
    """Tests for BasicMetadataStrategy."""

    def test_create_basic_metadata(self):
        """Test creating basic metadata with minimal fields."""
        strategy = BasicMetadataStrategy()
        context = MetadataContext(
            record={'id': '123', 'content': 'full content'},
            field_name='content',
            field_value='full content',
            chunk='chunk text',
            chunk_index=1,
            total_chunks=3,
        )

        metadata = strategy.create_metadata(context)

        assert metadata['source_field'] == 'content'
        assert metadata['chunk_index'] == 1
        assert metadata['total_chunks'] == 3
        assert len(metadata) == 3  # Only basic fields

    def test_basic_metadata_multiple_chunks(self):
        """Test basic metadata for different chunk indices."""
        strategy = BasicMetadataStrategy()

        for idx in range(1, 4):
            context = MetadataContext(
                record={'id': '123'},
                field_name='description',
                field_value='full text',
                chunk=f'chunk {idx}',
                chunk_index=idx,
                total_chunks=3,
            )
            metadata = strategy.create_metadata(context)

            assert metadata['chunk_index'] == idx
            assert metadata['total_chunks'] == 3


class TestEnhancedMetadataStrategy:
    """Tests for EnhancedMetadataStrategy."""

    def test_create_enhanced_metadata_with_chunk_id(self):
        """Test enhanced metadata with chunk ID field."""
        config = {'chunk_id_field': 'chunk_id', 'add_chunk_info': True}
        strategy = EnhancedMetadataStrategy(config, 'cl100k_base')

        context = MetadataContext(
            record={'id': '123', 'content': 'test content'},
            field_name='content',
            field_value='full content text',
            chunk='chunk text',
            chunk_index=2,
            total_chunks=5,
        )

        metadata = strategy.create_metadata(context)

        assert metadata['source_field'] == 'content'
        assert metadata['chunk_index'] == 2
        assert metadata['total_chunks'] == 5
        assert metadata['chunk_id'] == '123_content_2'

    def test_create_enhanced_metadata_with_original_record_id(self):
        """Test enhanced metadata with original record ID field."""
        config = {'original_record_id': 'parent_id', 'add_chunk_info': True}
        strategy = EnhancedMetadataStrategy(config, 'cl100k_base')

        context = MetadataContext(
            record={'id': 'abc-456', 'content': 'test'},
            field_name='content',
            field_value='full content',
            chunk='chunk',
            chunk_index=1,
            total_chunks=1,
        )

        metadata = strategy.create_metadata(context)

        assert metadata['parent_id'] == 'abc-456'

    def test_create_enhanced_metadata_with_char_positions(self):
        """Test enhanced metadata with character position information."""
        config = {'add_char_positions': True, 'add_chunk_info': True}
        strategy = EnhancedMetadataStrategy(config, 'cl100k_base')

        context = MetadataContext(
            record={'id': '123'},
            field_name='content',
            field_value='a' * 1000,
            chunk='a' * 100,
            chunk_index=2,
            total_chunks=10,
        )

        metadata = strategy.create_metadata(context)

        assert 'chunk_start_char' in metadata
        assert 'chunk_end_char' in metadata
        assert 'chunk_size_chars' in metadata
        assert 'original_field_size_chars' in metadata
        assert metadata['chunk_size_chars'] == 100
        assert metadata['original_field_size_chars'] == 1000

    def test_create_enhanced_metadata_with_token_counts(self):
        """Test enhanced metadata with token count information."""
        config = {'add_token_counts': True, 'add_chunk_info': True}
        strategy = EnhancedMetadataStrategy(config, 'cl100k_base')

        context = MetadataContext(
            record={'id': '123'},
            field_name='content',
            field_value='This is the full content text with many words.',
            chunk='This is a chunk.',
            chunk_index=1,
            total_chunks=3,
        )

        metadata = strategy.create_metadata(context)

        assert 'chunk_size_tokens' in metadata
        assert 'original_field_size_tokens' in metadata
        assert isinstance(metadata['chunk_size_tokens'], int)
        assert isinstance(metadata['original_field_size_tokens'], int)
        assert metadata['chunk_size_tokens'] > 0
        assert metadata['original_field_size_tokens'] > 0

    def test_create_enhanced_metadata_with_all_features(self):
        """Test enhanced metadata with all features enabled."""
        config = {
            'chunk_id_field': 'chunk_id',
            'original_record_id': 'parent_id',
            'add_char_positions': True,
            'add_token_counts': True,
            'add_chunk_info': True,
        }
        strategy = EnhancedMetadataStrategy(config, 'cl100k_base')

        context = MetadataContext(
            record={'id': '123', 'title': 'Test Document'},
            field_name='content',
            field_value='Full content with multiple words and sentences.',
            chunk='Full content with',
            chunk_index=1,
            total_chunks=2,
        )

        metadata = strategy.create_metadata(context)

        # Basic fields
        assert metadata['source_field'] == 'content'
        assert metadata['chunk_index'] == 1
        assert metadata['total_chunks'] == 2

        # Enhanced fields
        assert 'chunk_id' in metadata
        assert 'parent_id' in metadata
        assert 'chunk_start_char' in metadata
        assert 'chunk_end_char' in metadata
        assert 'chunk_size_chars' in metadata
        assert 'original_field_size_chars' in metadata
        assert 'chunk_size_tokens' in metadata
        assert 'original_field_size_tokens' in metadata

    def test_enhanced_metadata_without_record_id(self):
        """Test enhanced metadata when record has no id field."""
        config = {'chunk_id_field': 'chunk_id', 'add_chunk_info': True}
        strategy = EnhancedMetadataStrategy(config, 'cl100k_base')

        context = MetadataContext(
            record={'content': 'test'},  # No 'id' field
            field_name='content',
            field_value='test',
            chunk='test',
            chunk_index=1,
            total_chunks=1,
        )

        metadata = strategy.create_metadata(context)

        # Should use 'unknown' when id is missing
        assert metadata['chunk_id'] == 'unknown_content_1'

    def test_enhanced_metadata_skips_missing_parent_id(self):
        """Test that original_record_id is skipped when record has no id."""
        config = {'original_record_id': 'parent_id', 'add_chunk_info': True}
        strategy = EnhancedMetadataStrategy(config, 'cl100k_base')

        context = MetadataContext(
            record={'content': 'test'},  # No 'id' field
            field_name='content',
            field_value='test',
            chunk='test',
            chunk_index=1,
            total_chunks=1,
        )

        metadata = strategy.create_metadata(context)

        # parent_id should not be in metadata when record has no id
        assert 'parent_id' not in metadata


class TestMetadataStrategyComparison:
    """Tests comparing different metadata strategies."""

    def test_basic_vs_enhanced_metadata(self):
        """Test that enhanced metadata contains more fields than basic."""
        basic_strategy = BasicMetadataStrategy()
        enhanced_config = {
            'chunk_id_field': 'chunk_id',
            'add_char_positions': True,
            'add_chunk_info': True,
        }
        enhanced_strategy = EnhancedMetadataStrategy(enhanced_config, 'cl100k_base')

        context = MetadataContext(
            record={'id': '123'},
            field_name='content',
            field_value='Full content',
            chunk='chunk',
            chunk_index=1,
            total_chunks=1,
        )

        basic_metadata = basic_strategy.create_metadata(context)
        enhanced_metadata = enhanced_strategy.create_metadata(context)

        # Basic should have 3 fields
        assert len(basic_metadata) == 3

        # Enhanced should have more
        assert len(enhanced_metadata) > len(basic_metadata)

    def test_metadata_context_dataclass(self):
        """Test MetadataContext dataclass creation."""
        context = MetadataContext(
            record={'id': '123'},
            field_name='content',
            field_value='full text',
            chunk='chunk text',
            chunk_index=2,
            total_chunks=5,
        )

        assert context.record == {'id': '123'}
        assert context.field_name == 'content'
        assert context.field_value == 'full text'
        assert context.chunk == 'chunk text'
        assert context.chunk_index == 2
        assert context.total_chunks == 5
