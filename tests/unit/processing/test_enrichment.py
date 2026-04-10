"""Tests for LineageEnricher index-based parent lookup via source_mapping."""

from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)


def _make_context(source_data, is_first_stage=False):
    """Create a ProcessingContext with the given source_data."""
    return ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name="dedup_tool",
        is_first_stage=is_first_stage,
        source_data=source_data,
    )


def _make_source_item(source_guid, node_id, lineage=None):
    """Create a source data item with lineage."""
    item = {
        "source_guid": source_guid,
        "node_id": node_id,
        "lineage": lineage if lineage is not None else [node_id],
        "content": {"data": f"from_{node_id}"},
    }
    return item


class TestLineageEnricherSourceMapping:
    """Tests for source_mapping-based lineage resolution."""

    def test_one_to_one_mapping_distinct_lineage(self):
        """5 inputs sharing source_guid, one-to-one mapping -> 5 distinct lineage chains."""
        shared_guid = "shared-guid-aaa"
        source_data = [_make_source_item(shared_guid, f"flatten_node_{i}") for i in range(5)]

        # 5 outputs, each mapped to a different input
        output_data = [
            {"content": {"question": f"Q{i}"}, "source_guid": shared_guid} for i in range(5)
        ]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,
            source_mapping={0: 0, 1: 1, 2: 2, 3: 3, 4: 4},
        )

        context = _make_context(source_data)
        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        # Each output should have lineage from its specific input, not the first match
        for i in range(5):
            item = enriched.data[i]
            assert "lineage" in item
            # The lineage should include the specific parent node
            assert f"flatten_node_{i}" in item["lineage"]

    def test_no_mapping_falls_back_to_source_guid_scan(self):
        """When source_mapping is None, existing source_guid scan behavior is preserved."""
        source_data = [
            _make_source_item("guid-a", "node_a"),
            _make_source_item("guid-b", "node_b"),
        ]

        output_data = [
            {"content": {"val": 1}, "source_guid": "guid-a"},
            {"content": {"val": 2}, "source_guid": "guid-b"},
        ]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,
            source_mapping=None,  # No mapping -> fallback
        )

        context = _make_context(source_data)
        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        # Per-item source_guid lookup should still work
        assert "node_a" in enriched.data[0]["lineage"]
        assert "node_b" in enriched.data[1]["lineage"]

    def test_many_to_one_mapping_uses_lineage_tracking_from_sources(self):
        """3 inputs merged into 1 output -> output gets lineage_sources with all 3 parent node_ids."""
        source_data = [
            _make_source_item("guid-a", "input_0"),
            _make_source_item("guid-b", "input_1"),
            _make_source_item("guid-c", "input_2"),
        ]

        output_data = [
            {"content": {"merged": True}},
        ]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,
            source_mapping={0: [0, 1, 2]},
        )

        context = _make_context(source_data)
        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        item = enriched.data[0]
        assert "lineage" in item
        # Many-to-one should produce lineage_sources
        assert "lineage_sources" in item
        assert len(item["lineage_sources"]) == 3
        assert "input_0" in item["lineage_sources"]
        assert "input_1" in item["lineage_sources"]
        assert "input_2" in item["lineage_sources"]

    def test_out_of_bounds_source_idx_handled_safely(self):
        """Source index beyond source_data length should not crash."""
        source_data = [
            _make_source_item("guid-a", "node_0"),
        ]

        output_data = [
            {"content": {"val": 1}},
        ]
        # source_mapping points to index 5, which is out of bounds
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,
            source_mapping={0: 5},
        )

        context = _make_context(source_data)
        enricher = LineageEnricher()
        # Should not raise
        enriched = enricher.enrich(result, context)
        assert enriched.data[0]["lineage"] is not None

    def test_output_index_not_in_mapping_falls_back(self):
        """Output index not present in source_mapping falls back to source_guid scan."""
        source_data = [
            _make_source_item("guid-a", "node_0"),
            _make_source_item("guid-b", "node_1"),
        ]

        output_data = [
            {"content": {"val": 1}, "source_guid": "guid-a"},
            {"content": {"val": 2}, "source_guid": "guid-b"},
        ]
        # Only map output 0; output 1 should fall back to source_guid scan
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,
            source_mapping={0: 0},
        )

        context = _make_context(source_data)
        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        # Output 0: uses source_mapping -> parent is node_0
        assert "node_0" in enriched.data[0]["lineage"]
        # Output 1: not in mapping, falls back to source_guid scan -> parent is node_1
        assert "node_1" in enriched.data[1]["lineage"]

    def test_source_mapping_with_none_source_data_ignored(self):
        """When source_data is None, source_mapping is ignored (has_source_mapping = False)."""
        output_data = [
            {"content": {"val": 1}},
        ]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,
            source_mapping={0: 0},
        )

        # source_data is empty list (default), context.source_data is not None but empty
        # has_source_mapping = True but index lookup will just skip (out of bounds)
        context = _make_context(source_data=[], is_first_stage=True)
        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)
        assert enriched.data[0]["lineage"] is not None

    def test_filtered_result_unchanged(self):
        """FILTERED results should pass through without modification."""
        result = ProcessingResult(
            status=ProcessingStatus.FILTERED,
            data=[],
            source_mapping={0: 0},
        )
        context = _make_context(source_data=[])
        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)
        assert enriched.status == ProcessingStatus.FILTERED

    def test_many_to_one_out_of_bounds_indices_skipped(self):
        """Many-to-one with some out-of-bounds indices should skip those safely."""
        source_data = [
            _make_source_item("guid-a", "input_0"),
        ]

        output_data = [
            {"content": {"merged": True}},
        ]
        # Index 0 is valid, indices 5 and 10 are out of bounds
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,
            source_mapping={0: [0, 5, 10]},
        )

        context = _make_context(source_data)
        enricher = LineageEnricher()
        enriched = enricher.enrich(result, context)

        item = enriched.data[0]
        assert "lineage" in item
        # Only valid index 0 should be in the sources
        assert item["node_id"] is not None
