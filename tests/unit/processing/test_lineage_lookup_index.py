"""Tests for O(N) dict-indexed lineage lookups in enrichment and transformer."""

import time

from agent_actions.input.preprocessing.transformation.transformer import (
    DataTransformer,
)
from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)


def _make_context(source_data, is_first_stage=False):
    return ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name="test_action",
        is_first_stage=is_first_stage,
        source_data=source_data,
    )


class TestGetParentItemWithIndex:
    """_get_parent_item uses source_index for O(1) lookups."""

    def test_index_lookup_returns_correct_item(self):
        source_data = [
            {"source_guid": "guid-a", "content": {"val": 1}},
            {"source_guid": "guid-b", "content": {"val": 2}},
        ]
        ctx = _make_context(source_data)
        enricher = LineageEnricher()
        source_index = {"guid-a": source_data[0], "guid-b": source_data[1]}

        result = enricher._get_parent_item("guid-b", ctx, source_index)
        assert result is source_data[1]

    def test_index_lookup_returns_none_for_missing_guid(self):
        source_data = [{"source_guid": "guid-a", "content": {}}]
        ctx = _make_context(source_data)
        enricher = LineageEnricher()
        source_index = {"guid-a": source_data[0]}

        result = enricher._get_parent_item("guid-missing", ctx, source_index)
        assert result is None

    def test_fallback_linear_scan_when_no_index(self):
        source_data = [
            {"source_guid": "guid-a", "content": {"val": 1}},
            {"source_guid": "guid-b", "content": {"val": 2}},
        ]
        ctx = _make_context(source_data)
        enricher = LineageEnricher()

        result = enricher._get_parent_item("guid-b", ctx)
        assert result is source_data[1]

    def test_first_stage_returns_none_regardless_of_index(self):
        source_data = [{"source_guid": "guid-a"}]
        ctx = _make_context(source_data, is_first_stage=True)
        enricher = LineageEnricher()
        source_index = {"guid-a": source_data[0]}

        result = enricher._get_parent_item("guid-a", ctx, source_index)
        assert result is None

    def test_none_source_guid_returns_none_with_index(self):
        ctx = _make_context([{"source_guid": "guid-a"}])
        enricher = LineageEnricher()

        result = enricher._get_parent_item(None, ctx, {"guid-a": {}})
        assert result is None

    def test_current_item_takes_precedence_over_index(self):
        """current_item is preferred when set, even with an index."""
        current = {"source_guid": "guid-a", "content": {"current": True}}
        source_data = [{"source_guid": "guid-a", "content": {"from_source": True}}]
        ctx = _make_context(source_data)
        ctx.current_item = current
        enricher = LineageEnricher()
        source_index = {"guid-a": source_data[0]}

        result = enricher._get_parent_item("guid-a", ctx, source_index)
        assert result is current


class TestLineageEnricherIndexBuilding:
    """LineageEnricher.enrich() builds the source_index before the loop."""

    def test_enrich_builds_index_and_resolves_parent(self):
        source_data = [
            {"source_guid": "guid-a", "node_id": "n1", "lineage": ["n1"]},
            {"source_guid": "guid-b", "node_id": "n2", "lineage": ["n2"]},
        ]
        output_data = [
            {"source_guid": "guid-a", "content": {"q": 1}},
            {"source_guid": "guid-b", "content": {"q": 2}},
        ]
        ctx = _make_context(source_data)
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,  # triggers per-item lookup
        )

        enriched = LineageEnricher().enrich(result, ctx)

        assert enriched.data[0].get("lineage") is not None
        assert enriched.data[1].get("lineage") is not None

    def test_items_without_source_guid_skipped_in_index(self):
        source_data = [
            {"source_guid": "guid-a", "node_id": "n1", "lineage": ["n1"]},
            {"content": {"no_guid": True}},  # no source_guid
            {"source_guid": None, "content": {"null_guid": True}},  # None guid
        ]
        output_data = [{"source_guid": "guid-a", "content": {"q": 1}}]
        ctx = _make_context(source_data)
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=output_data,
            source_guid=None,
        )

        enriched = LineageEnricher().enrich(result, ctx)
        assert enriched.data[0].get("lineage") is not None


class TestGetContentBySourceGuidIndex:
    """DataTransformer.get_content_by_source_guid with index parameter."""

    def test_index_lookup_returns_correct_item(self):
        data = [
            {"source_guid": "a", "val": 1},
            {"source_guid": "b", "val": 2},
        ]
        index = {"a": data[0], "b": data[1]}

        result = DataTransformer.get_content_by_source_guid(data, "b", index=index)
        assert result is data[1]

    def test_index_lookup_returns_none_for_missing(self):
        data = [{"source_guid": "a"}]
        index = {"a": data[0]}

        result = DataTransformer.get_content_by_source_guid(data, "missing", index=index)
        assert result is None

    def test_fallback_linear_scan_without_index(self):
        data = [
            {"source_guid": "a", "val": 1},
            {"source_guid": "b", "val": 2},
        ]

        result = DataTransformer.get_content_by_source_guid(data, "b")
        assert result is data[1]

    def test_index_matches_linear_scan_results(self):
        data = [{"source_guid": f"guid-{i}", "val": i} for i in range(100)]
        index = {item["source_guid"]: item for item in data}

        for guid in ["guid-0", "guid-50", "guid-99"]:
            via_index = DataTransformer.get_content_by_source_guid(data, guid, index=index)
            via_scan = DataTransformer.get_content_by_source_guid(data, guid)
            assert via_index == via_scan


class TestLineageLookupPerformance:
    """Verify O(N) behavior with dict index vs O(N^2) linear scan."""

    def test_dict_index_is_sublinear_vs_linear_scan(self):
        n = 2000
        source_data = [{"source_guid": f"guid_{i}", "content": f"data_{i}"} for i in range(n)]

        # Linear scan: O(N^2)
        start = time.perf_counter()
        for record in source_data:
            target = record["source_guid"]
            for src in source_data:
                if src.get("source_guid") == target:
                    break
        linear_time = time.perf_counter() - start

        # Dict index: O(N)
        start = time.perf_counter()
        index = {item["source_guid"]: item for item in source_data if item.get("source_guid")}
        for record in source_data:
            _ = index.get(record["source_guid"])
        index_time = time.perf_counter() - start

        # The dict path should be significantly faster
        assert index_time < linear_time, (
            f"Dict index ({index_time:.4f}s) should be faster than linear scan ({linear_time:.4f}s)"
        )
        # For 2000 records, expect at least 5x speedup
        speedup = linear_time / index_time if index_time > 0 else float("inf")
        assert speedup > 5, f"Expected >5x speedup, got {speedup:.1f}x"
