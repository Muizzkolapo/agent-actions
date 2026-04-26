"""Tests for _apply_context_passthrough Path B (fallback extraction).

Path A: passthrough fields pre-stored in BatchContextMetadata during preparation.
Path B: no pre-stored fields — extracts from original record's namespaced content at result time.

Path B triggers when context_scope.passthrough is configured but
BatchContextMetadata has no stored passthrough fields (e.g. recovery batches
that rebuild context without full preparation).
"""

from typing import Any

from agent_actions.llm.batch.processing.result_processor import (
    BatchProcessingContext,
    BatchResultProcessor,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_context(
    context_map: dict[str, Any],
    agent_config: dict[str, Any] | None = None,
) -> BatchProcessingContext:
    """Build a minimal BatchProcessingContext for passthrough testing."""
    return BatchProcessingContext(
        batch_results=[],
        context_map=context_map,
        output_directory=None,
        agent_config=agent_config,
    )


def _make_context_map_entry(**extra) -> dict[str, Any]:
    """Build a context_map entry (same shape as a data row with batch metadata)."""
    base = {
        "target_id": "rec_001",
        "source_guid": "src_001",
    }
    base.update(extra)
    return base


# ── Path B: merges passthrough fields from namespaced content ────────


class TestPathBPassthroughMerge:
    """Path B extracts passthrough values from original record's namespaced content."""

    def test_single_field_merges_into_generated_items(self):
        """Path B merges a single passthrough field from a namespace."""
        entry = _make_context_map_entry(
            content={"classify": {"category": "tech", "confidence": 0.9}}
        )
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["classify.category"]},
            },
        )
        generated = [{"summary": "AI overview"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert len(result) == 1
        assert result[0]["summary"] == "AI overview"
        assert result[0]["classify"] == {"category": "tech"}

    def test_multiple_fields_same_namespace(self):
        """Path B merges multiple fields from the same namespace."""
        entry = _make_context_map_entry(
            content={"source": {"text": "hello", "lang": "en", "internal": "x"}}
        )
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {
                    "passthrough": ["source.text", "source.lang"],
                },
            },
        )
        generated = [{"output": "world"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result[0]["source"] == {"text": "hello", "lang": "en"}
        assert result[0]["output"] == "world"

    def test_fields_from_multiple_namespaces(self):
        """Path B merges fields from different namespaces."""
        entry = _make_context_map_entry(
            content={
                "classify": {"category": "tech"},
                "extract": {"record_id": "abc"},
            }
        )
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {
                    "passthrough": ["classify.category", "extract.record_id"],
                },
            },
        )
        generated = [{"summary": "test"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result[0]["classify"] == {"category": "tech"}
        assert result[0]["extract"] == {"record_id": "abc"}
        assert result[0]["summary"] == "test"

    def test_wildcard_merges_entire_namespace(self):
        """Path B with wildcard passthrough merges all fields from a namespace."""
        entry = _make_context_map_entry(
            content={"source": {"text": "hello", "lang": "en", "count": 5}}
        )
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["source.*"]},
            },
        )
        generated = [{"output": "result"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result[0]["source"] == {"text": "hello", "lang": "en", "count": 5}

    def test_multiple_generated_items_all_receive_passthrough(self):
        """All items in generated_list get passthrough fields merged."""
        entry = _make_context_map_entry(content={"classify": {"category": "tech"}})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["classify.category"]},
            },
        )
        generated = [{"item": 1}, {"item": 2}, {"item": 3}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert len(result) == 3
        for item in result:
            assert item["classify"] == {"category": "tech"}


# ── Path B: edge cases and missing data ──────────────────────────────


class TestPathBEdgeCases:
    """Path B handles missing data gracefully — no crash, no silent corruption."""

    def test_missing_content_key_returns_unchanged(self):
        """If original record has no content, generated items are returned unchanged."""
        entry = _make_context_map_entry()  # no "content" key
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["classify.category"]},
            },
        )
        generated = [{"summary": "test"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result == [{"summary": "test"}]

    def test_missing_namespace_skips_field(self):
        """If the referenced namespace doesn't exist, that field is skipped."""
        entry = _make_context_map_entry(content={"classify": {"category": "tech"}})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {
                    "passthrough": ["classify.category", "nonexistent.field"],
                },
            },
        )
        generated = [{"summary": "test"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result[0]["classify"] == {"category": "tech"}
        assert "nonexistent" not in result[0]

    def test_missing_field_in_existing_namespace_skips(self):
        """If the namespace exists but the field doesn't, that field is skipped."""
        entry = _make_context_map_entry(content={"classify": {"category": "tech"}})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {
                    "passthrough": ["classify.no_such_field"],
                },
            },
        )
        generated = [{"summary": "test"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result == [{"summary": "test"}]

    def test_non_dict_items_skipped(self):
        """Non-dict items in generated_list are passed through unchanged."""
        entry = _make_context_map_entry(content={"classify": {"category": "tech"}})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["classify.category"]},
            },
        )
        generated = [{"summary": "test"}, "raw_string", 42]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result[0]["classify"] == {"category": "tech"}
        assert result[1] == "raw_string"
        assert result[2] == 42

    def test_empty_generated_list_returns_empty(self):
        """Empty generated_list returns empty list."""
        entry = _make_context_map_entry(content={"classify": {"category": "tech"}})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["classify.category"]},
            },
        )
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", [], entry)

        assert result == []

    def test_namespace_value_not_dict_skipped(self):
        """If a namespace maps to a non-dict value, it's skipped."""
        entry = _make_context_map_entry(content={"classify": "not_a_dict"})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["classify.category"]},
            },
        )
        generated = [{"summary": "test"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result == [{"summary": "test"}]

    def test_malformed_field_ref_skipped(self):
        """Malformed refs (no dot) are skipped; valid sibling refs still merge."""
        entry = _make_context_map_entry(content={"classify": {"category": "tech"}})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {
                    "passthrough": ["no_dot_here", "classify.category", ""],
                },
            },
        )
        generated = [{"summary": "test"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        assert result[0]["classify"] == {"category": "tech"}
        assert result[0]["summary"] == "test"

    def test_wildcard_on_empty_namespace_skipped(self):
        """Wildcard on an empty namespace produces no merge."""
        entry = _make_context_map_entry(content={"source": {}})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["source.*"]},
            },
        )
        generated = [{"output": "result"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        # Empty namespace produces empty passthrough_data → no merge
        assert result == [{"output": "result"}]


# ── Path A takes precedence over Path B ──────────────────────────────


class TestPathAPrecedence:
    """When pre-stored passthrough fields exist, Path A is used (not Path B)."""

    def test_stored_passthrough_used_over_fallback(self):
        """Path A passthrough from BatchContextMetadata takes priority."""
        entry = _make_context_map_entry(
            content={"classify": {"category": "tech"}},
            _passthrough_fields={"classify": {"category": "STORED_VALUE"}},
        )
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={
                "context_scope": {"passthrough": ["classify.category"]},
            },
        )
        generated = [{"summary": "test"}]
        processor = BatchResultProcessor()

        result = processor._apply_context_passthrough(ctx, "rec_001", generated, entry)

        # Path A's stored value wins, not Path B's extraction from content
        assert result[0]["classify"] == {"category": "STORED_VALUE"}
