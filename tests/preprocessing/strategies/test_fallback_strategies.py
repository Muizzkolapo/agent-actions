"""Tests for fallback strategies — Truncate must not silently mimic Skip."""

from agent_actions.input.preprocessing.chunking.strategies.fallback_strategies import (
    PreserveOriginalStrategy,
    SkipStrategy,
    TruncateStrategy,
)


class TestTruncateStrategyChunkingError:
    """TruncateStrategy.handle_chunking_error must NOT drop records like SkipStrategy."""

    def test_truncate_emits_single_chunk_record_not_empty_list(self):
        """Truncate on chunking error must emit one record, not drop it."""
        strategy = TruncateStrategy(truncate_at=100)
        record = {"id": "r1", "content": "x" * 500, "extra": "kept"}

        result = strategy.handle_chunking_error(record, "content", "tokenize failed")

        assert len(result) == 1, "Truncate must preserve the record, not drop it"

    def test_truncate_actually_truncates_the_failing_field(self):
        """The failing field is truncated to truncate_at chars."""
        strategy = TruncateStrategy(truncate_at=50)
        record = {"id": "r1", "content": "abcdefghij" * 100}

        result = strategy.handle_chunking_error(record, "content", "tokenize failed")

        assert len(result[0]["content"]) == 50
        assert result[0]["content"] == "abcdefghij" * 5

    def test_truncate_preserves_other_fields_unchanged(self):
        """Non-failing fields are passed through untouched."""
        strategy = TruncateStrategy(truncate_at=100)
        record = {"id": "r1", "content": "x" * 500, "url": "https://example.com", "n": 42}

        result = strategy.handle_chunking_error(record, "content", "err")

        assert result[0]["id"] == "r1"
        assert result[0]["url"] == "https://example.com"
        assert result[0]["n"] == 42

    def test_truncate_attaches_chunk_info_metadata(self):
        """Result carries chunk_info documenting the truncation."""
        strategy = TruncateStrategy(truncate_at=200)
        record = {"id": "r1", "content": "x" * 500}

        result = strategy.handle_chunking_error(record, "content", "tokenize failed")

        info = result[0]["chunk_info"]
        assert info["source_field"] == "content"
        assert info["chunk_index"] == 1
        assert info["total_chunks"] == 1
        assert info["chunking_error"] == "tokenize failed"
        assert info["fallback_applied"] == "truncate_on_error"
        assert info["truncated_at"] == 200

    def test_truncate_is_distinct_from_skip(self):
        """The whole point: Truncate.handle_chunking_error != Skip.handle_chunking_error."""
        truncate = TruncateStrategy(truncate_at=100)
        skip = SkipStrategy()
        record = {"id": "r1", "content": "data"}

        truncate_result = truncate.handle_chunking_error(record, "content", "err")
        skip_result = skip.handle_chunking_error(record, "content", "err")

        assert truncate_result != skip_result
        assert skip_result == []
        assert len(truncate_result) == 1

    def test_truncate_does_not_mutate_input_record(self):
        """The original record dict is not mutated."""
        strategy = TruncateStrategy(truncate_at=10)
        record = {"id": "r1", "content": "x" * 100}
        original_content = record["content"]

        strategy.handle_chunking_error(record, "content", "err")

        assert record["content"] == original_content
        assert "chunk_info" not in record

    def test_truncate_handles_non_string_field_gracefully(self):
        """Non-string field values are preserved (truncation is a string op)."""
        strategy = TruncateStrategy(truncate_at=100)
        record = {"id": "r1", "count": 42}

        result = strategy.handle_chunking_error(record, "count", "err")

        assert result[0]["count"] == 42
        assert result[0]["chunk_info"]["fallback_applied"] == "truncate_on_error"

    def test_truncate_at_default_matches_chunker_config(self):
        """Default truncate_at mirrors ChunkerConfig.truncate_at (50000)."""
        strategy = TruncateStrategy()
        assert strategy.truncate_at == 50000

    def test_truncate_handles_missing_field(self):
        """Missing field still produces a record with empty truncated content."""
        strategy = TruncateStrategy(truncate_at=100)
        record = {"id": "r1"}

        result = strategy.handle_chunking_error(record, "content", "err")

        assert len(result) == 1
        assert result[0]["id"] == "r1"


class TestTruncateAndPreserveSemantics:
    """Sanity: each strategy retains its established semantic."""

    def test_preserve_keeps_full_content(self):
        strategy = PreserveOriginalStrategy()
        record = {"id": "r1", "content": "x" * 500}
        result = strategy.handle_chunking_error(record, "content", "err")
        assert result[0]["content"] == "x" * 500

    def test_skip_drops_record(self):
        strategy = SkipStrategy()
        result = strategy.handle_chunking_error({"id": "r1"}, "content", "err")
        assert result == []
