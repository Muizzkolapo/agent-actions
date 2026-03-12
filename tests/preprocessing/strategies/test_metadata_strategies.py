"""Tests for metadata strategies."""

import pytest

from agent_actions.input.preprocessing.chunking.strategies.metadata_strategies import (
    EnhancedMetadataStrategy,
    MetadataContext,
)


class TestEnhancedMetadataStrategy:
    """Tests for EnhancedMetadataStrategy."""

    @staticmethod
    def _fake_token_count(value: str, _: str = "") -> int:
        """Deterministic token counter that avoids network calls to tiktoken."""
        return len(value.split())

    def test_create_enhanced_metadata_with_token_counts(self, monkeypatch: pytest.MonkeyPatch):
        """Test enhanced metadata with token count information."""
        monkeypatch.setattr(
            "agent_actions.input.preprocessing.chunking.strategies.metadata_strategies.Tokenizer.num_tokens_from_string",
            self._fake_token_count,
        )
        config = {"add_token_counts": True, "add_chunk_info": True}
        strategy = EnhancedMetadataStrategy(config, "cl100k_base")

        context = MetadataContext(
            record={"id": "123"},
            field_name="content",
            field_value="This is the full content text with many words.",
            chunk="This is a chunk.",
            chunk_index=1,
            total_chunks=3,
        )

        metadata = strategy.create_metadata(context)

        assert "chunk_size_tokens" in metadata
        assert "original_field_size_tokens" in metadata
        assert isinstance(metadata["chunk_size_tokens"], int)
        assert isinstance(metadata["original_field_size_tokens"], int)
        assert metadata["chunk_size_tokens"] > 0
        assert metadata["original_field_size_tokens"] > 0

    def test_create_enhanced_metadata_with_char_positions(self):
        """Test enhanced metadata with character position information."""
        config = {"add_char_positions": True, "add_chunk_info": True}
        strategy = EnhancedMetadataStrategy(config, "cl100k_base")

        context = MetadataContext(
            record={"id": "123"},
            field_name="content",
            field_value="a" * 1000,
            chunk="a" * 100,
            chunk_index=2,
            total_chunks=10,
        )

        metadata = strategy.create_metadata(context)

        assert "chunk_start_char" in metadata
        assert "chunk_end_char" in metadata
        assert "chunk_size_chars" in metadata
        assert "original_field_size_chars" in metadata
        assert metadata["chunk_size_chars"] == 100
        assert metadata["original_field_size_chars"] == 1000

    def test_create_enhanced_metadata_with_all_features(self, monkeypatch: pytest.MonkeyPatch):
        """Test enhanced metadata with all features enabled."""
        monkeypatch.setattr(
            "agent_actions.input.preprocessing.chunking.strategies.metadata_strategies.Tokenizer.num_tokens_from_string",
            self._fake_token_count,
        )
        config = {
            "chunk_id_field": "chunk_id",
            "original_record_id": "parent_id",
            "add_char_positions": True,
            "add_token_counts": True,
            "add_chunk_info": True,
        }
        strategy = EnhancedMetadataStrategy(config, "cl100k_base")

        context = MetadataContext(
            record={"id": "123", "title": "Test Document"},
            field_name="content",
            field_value="Full content with multiple words and sentences.",
            chunk="Full content with",
            chunk_index=1,
            total_chunks=2,
        )

        metadata = strategy.create_metadata(context)

        # Basic fields
        assert metadata["source_field"] == "content"
        assert metadata["chunk_index"] == 1
        assert metadata["total_chunks"] == 2

        # Enhanced fields
        assert "chunk_id" in metadata
        assert "parent_id" in metadata
        assert "chunk_start_char" in metadata
        assert "chunk_end_char" in metadata
        assert "chunk_size_chars" in metadata
        assert "original_field_size_chars" in metadata
        assert "chunk_size_tokens" in metadata
        assert "original_field_size_tokens" in metadata

    def test_enhanced_metadata_without_record_id(self):
        """Test enhanced metadata when record has no id field."""
        config = {"chunk_id_field": "chunk_id", "add_chunk_info": True}
        strategy = EnhancedMetadataStrategy(config, "cl100k_base")

        context = MetadataContext(
            record={"content": "test"},  # No 'id' field
            field_name="content",
            field_value="test",
            chunk="test",
            chunk_index=1,
            total_chunks=1,
        )

        metadata = strategy.create_metadata(context)

        # Should use 'unknown' when id is missing
        assert metadata["chunk_id"] == "unknown_content_1"

    def test_enhanced_metadata_skips_missing_parent_id(self):
        """Test that original_record_id is skipped when record has no id."""
        config = {"original_record_id": "parent_id", "add_chunk_info": True}
        strategy = EnhancedMetadataStrategy(config, "cl100k_base")

        context = MetadataContext(
            record={"content": "test"},  # No 'id' field
            field_name="content",
            field_value="test",
            chunk="test",
            chunk_index=1,
            total_chunks=1,
        )

        metadata = strategy.create_metadata(context)

        # parent_id should not be in metadata when record has no id
        assert "parent_id" not in metadata
