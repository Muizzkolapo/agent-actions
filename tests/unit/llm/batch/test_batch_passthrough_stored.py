"""Tests for _apply_context_passthrough — stored passthrough merge.

Passthrough fields are pre-extracted during batch preparation and stored in
BatchContextMetadata. At result processing time, stored fields are merged into
generated items.
"""

from typing import Any

from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
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


# ── Stored passthrough merges into generated items ───────────────────


class TestStoredPassthroughMerge:
    """Stored passthrough fields are merged into every generated item."""

    def test_single_namespace_field(self):
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"classify": {"category": "tech"}})
        ctx = _make_context(context_map={"rec_001": entry})
        processor = BatchResultStrategy()

        result = processor._apply_context_passthrough(ctx, "rec_001", [{"summary": "AI overview"}])

        assert len(result) == 1
        assert result[0]["summary"] == "AI overview"
        assert result[0]["classify"] == {"category": "tech"}

    def test_multiple_namespaces(self):
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(
            entry,
            {
                "classify": {"category": "tech"},
                "extract": {"record_id": "abc"},
            },
        )
        ctx = _make_context(context_map={"rec_001": entry})
        processor = BatchResultStrategy()

        result = processor._apply_context_passthrough(ctx, "rec_001", [{"summary": "test"}])

        assert result[0]["classify"] == {"category": "tech"}
        assert result[0]["extract"] == {"record_id": "abc"}
        assert result[0]["summary"] == "test"

    def test_all_generated_items_receive_passthrough(self):
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"classify": {"category": "tech"}})
        ctx = _make_context(context_map={"rec_001": entry})
        processor = BatchResultStrategy()

        result = processor._apply_context_passthrough(
            ctx, "rec_001", [{"item": 1}, {"item": 2}, {"item": 3}]
        )

        assert len(result) == 3
        for item in result:
            assert item["classify"] == {"category": "tech"}


# ── Edge cases ───────────────────────────────────────────────────────


class TestStoredPassthroughEdgeCases:
    """Edge cases: empty passthrough, non-dict items, empty list."""

    def test_empty_stored_passthrough_returns_unchanged(self):
        """When stored passthrough is empty dict, generated items are unchanged."""
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {})
        ctx = _make_context(context_map={"rec_001": entry})
        processor = BatchResultStrategy()

        result = processor._apply_context_passthrough(ctx, "rec_001", [{"summary": "test"}])

        assert result == [{"summary": "test"}]

    def test_no_stored_passthrough_returns_unchanged(self):
        """When no passthrough was stored at all, generated items are unchanged."""
        entry = _make_context_map_entry()
        ctx = _make_context(context_map={"rec_001": entry})
        processor = BatchResultStrategy()

        result = processor._apply_context_passthrough(ctx, "rec_001", [{"summary": "test"}])

        assert result == [{"summary": "test"}]

    def test_non_dict_items_passed_through(self):
        """Non-dict items in generated_list are passed through unchanged."""
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"classify": {"category": "tech"}})
        ctx = _make_context(context_map={"rec_001": entry})
        processor = BatchResultStrategy()

        result = processor._apply_context_passthrough(
            ctx, "rec_001", [{"summary": "test"}, "raw_string", 42]
        )

        assert result[0]["classify"] == {"category": "tech"}
        assert result[1] == "raw_string"
        assert result[2] == 42

    def test_empty_generated_list(self):
        """Empty generated_list returns empty list."""
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"classify": {"category": "tech"}})
        ctx = _make_context(context_map={"rec_001": entry})
        processor = BatchResultStrategy()

        result = processor._apply_context_passthrough(ctx, "rec_001", [])

        assert result == []

    def test_passthrough_does_not_fire_without_context_scope_config(self):
        """Even with agent_config having no context_scope, stored passthrough still applies."""
        entry = _make_context_map_entry()
        BatchContextMetadata.set_passthrough_fields(entry, {"source": {"id": "123"}})
        ctx = _make_context(
            context_map={"rec_001": entry},
            agent_config={"action_name": "test"},
        )
        processor = BatchResultStrategy()

        result = processor._apply_context_passthrough(ctx, "rec_001", [{"output": "val"}])

        assert result[0]["source"] == {"id": "123"}
        assert result[0]["output"] == "val"
