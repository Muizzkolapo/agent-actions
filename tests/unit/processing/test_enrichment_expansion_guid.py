"""Tests for LineageEnricher: expansion children get unique source_guids."""

from unittest.mock import MagicMock

from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus


def _make_context(action_name: str = "test_action") -> ProcessingContext:
    """Create a minimal ProcessingContext for testing."""
    ctx = MagicMock(spec=ProcessingContext)
    ctx.action_name = action_name
    ctx.agent_name = action_name
    ctx.is_first_stage = True
    ctx.source_data = None
    ctx.parent_records = []
    ctx.record_index = 0
    ctx.agent_config = {}
    return ctx


class TestExpansionSourceGuidUniqueness:
    """Expansion children each get their own source_guid."""

    def test_expansion_children_get_unique_source_guids(self):
        parent_guid = "parent-guid-123"
        items = [
            {"source_guid": parent_guid, "target_id": "tid-1", "content": "a"},
            {"source_guid": parent_guid, "target_id": "tid-1", "content": "b"},
            {"source_guid": parent_guid, "target_id": "tid-1", "content": "c"},
        ]
        result = ProcessingResult(
            data=items,
            status=ProcessingStatus.SUCCESS,
            is_expansion=True,
        )
        context = _make_context()

        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        source_guids = [item["source_guid"] for item in enriched.data]
        # All children should have unique source_guids
        assert len(set(source_guids)) == 3
        # None should be the parent's guid
        assert parent_guid not in source_guids

    def test_expansion_children_preserve_parent_source_guid(self):
        parent_guid = "parent-guid-456"
        items = [
            {"source_guid": parent_guid, "target_id": "tid-1", "content": "x"},
            {"source_guid": parent_guid, "target_id": "tid-1", "content": "y"},
        ]
        result = ProcessingResult(
            data=items,
            status=ProcessingStatus.SUCCESS,
            is_expansion=True,
        )
        context = _make_context()

        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        for item in enriched.data:
            assert item["parent_source_guid"] == parent_guid

    def test_nested_expansion_preserves_original_parent_source_guid(self):
        """Re-expanding an expansion child keeps the original pool-resolvable attribution."""
        items = [
            {
                "source_guid": "minted-gen1",
                "parent_source_guid": "original-staged-guid",
                "target_id": "tid-1",
                "content": "a",
            },
            {
                "source_guid": "minted-gen1",
                "parent_source_guid": "original-staged-guid",
                "target_id": "tid-1",
                "content": "b",
            },
        ]
        result = ProcessingResult(
            data=items,
            status=ProcessingStatus.SUCCESS,
            is_expansion=True,
        )
        context = _make_context()

        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        for item in enriched.data:
            assert item["parent_source_guid"] == "original-staged-guid"
            assert item["source_guid"] != "minted-gen1"

    def test_non_expansion_keeps_original_source_guid(self):
        original_guid = "keep-this-guid"
        items = [{"source_guid": original_guid, "content": "data"}]
        result = ProcessingResult(
            data=items,
            status=ProcessingStatus.SUCCESS,
            is_expansion=False,
        )
        context = _make_context()

        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        assert enriched.data[0]["source_guid"] == original_guid
        assert "parent_source_guid" not in enriched.data[0]
