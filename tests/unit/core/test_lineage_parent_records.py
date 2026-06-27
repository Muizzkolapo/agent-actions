"""LineageEnricher must extend downstream chains via parent_records."""

from __future__ import annotations

import pytest

from agent_actions.config.types import RunMode
from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.utils.correlation import VersionIdGenerator


@pytest.fixture(autouse=True)
def clear_correlation_registry():
    VersionIdGenerator.clear_version_correlation_registry()
    yield
    VersionIdGenerator.clear_version_correlation_registry()


def _make_context(
    parent_records: list[dict] | None = None,
    source_data: list[dict] | None = None,
) -> ProcessingContext:
    return ProcessingContext(
        agent_config={"agent_type": "stage_two"},
        agent_name="stage_two",
        mode=RunMode.ONLINE,
        is_first_stage=False,
        parent_records=parent_records or [],
        source_data=source_data or [],
    )


class TestParentRecordsLineagePropagation:
    """parent_records is preferred over source_data for parent lookup."""

    def test_downstream_lineage_extends_parent_chain(self):
        """The bug repro: a downstream record's lineage must include the parent's node_id."""
        # Stage-one output: has lineage (would be in parent_records).
        stage_one_node_id = "stage_one_abc123"
        parent = {
            "source_guid": "guid_1",
            "node_id": stage_one_node_id,
            "lineage": [stage_one_node_id],
            "content": {"stage_one": {"data": "value"}},
        }

        # Stage-two output before enrichment.
        stage_two_item = {
            "source_guid": "guid_1",
            "content": {"stage_two": {"derived": "from stage_one"}},
        }
        result = ProcessingResult.success(
            data=[stage_two_item],
            source_guid="guid_1",
        )

        # Raw seed records (no lineage) — what source_data would carry.
        raw_seed = [{"source_guid": "guid_1", "page_content": "raw text"}]

        context = _make_context(parent_records=[parent], source_data=raw_seed)
        enriched = LineageEnricher().enrich(result, context)

        enriched_item = enriched.data[0]
        assert "lineage" in enriched_item
        assert len(enriched_item["lineage"]) == 2, (
            f"Expected lineage to extend parent chain (2 entries), got {enriched_item['lineage']}"
        )
        assert enriched_item["lineage"][0] == stage_one_node_id, (
            "Parent node_id must be first in the chain"
        )
        assert enriched_item["lineage"][1] == enriched_item["node_id"], (
            "Self node_id must be the tail of the chain"
        )

    def test_parent_records_preferred_over_source_data(self):
        """When both are present, parent_records wins — even if source_data has the same source_guid."""
        parent_node_id = "stage_one_xyz789"
        parent = {
            "source_guid": "guid_shared",
            "node_id": parent_node_id,
            "lineage": [parent_node_id],
        }
        # source_data has the same source_guid but no lineage (raw seed shape).
        raw_seed = [{"source_guid": "guid_shared", "page_content": "raw"}]

        item = {"source_guid": "guid_shared", "content": {"stage_two": {"x": 1}}}
        result = ProcessingResult.success(data=[item], source_guid="guid_shared")

        context = _make_context(parent_records=[parent], source_data=raw_seed)
        enriched = LineageEnricher().enrich(result, context)

        enriched_item = enriched.data[0]
        # If source_data had won, lineage would be [self] (raw_seed has no lineage).
        assert len(enriched_item["lineage"]) == 2
        assert enriched_item["lineage"][0] == parent_node_id

    def test_falls_back_to_source_data_when_parent_records_empty(self):
        """No parent_records → look up parent in source_data (FILE-mode path)."""
        parent_node_id = "stage_one_file_mode"
        source_data_with_lineage = [
            {
                "source_guid": "guid_fm",
                "node_id": parent_node_id,
                "lineage": [parent_node_id],
            }
        ]
        item = {"source_guid": "guid_fm", "content": {"stage_two": {"y": 2}}}
        result = ProcessingResult.success(data=[item], source_guid="guid_fm")

        context = _make_context(parent_records=[], source_data=source_data_with_lineage)
        enriched = LineageEnricher().enrich(result, context)

        enriched_item = enriched.data[0]
        assert len(enriched_item["lineage"]) == 2
        assert enriched_item["lineage"][0] == parent_node_id

    def test_raw_seed_only_produces_self_lineage(self):
        """With neither parent_records nor lineage-bearing source_data, lineage is self-only."""
        raw_seed = [{"source_guid": "guid_solo", "page_content": "raw"}]
        item = {"source_guid": "guid_solo", "content": {"stage_two": {"z": 3}}}
        result = ProcessingResult.success(data=[item], source_guid="guid_solo")

        context = _make_context(parent_records=[], source_data=raw_seed)
        enriched = LineageEnricher().enrich(result, context)

        enriched_item = enriched.data[0]
        # parent_item is the raw seed (no lineage) → fallback to [node_id]
        assert enriched_item["lineage"] == [enriched_item["node_id"]]

    def test_first_stage_unchanged(self):
        """is_first_stage=True still returns no parent (source records get self-only lineage)."""
        parent = {
            "source_guid": "guid_first",
            "node_id": "irrelevant",
            "lineage": ["irrelevant"],
        }
        item = {"source_guid": "guid_first", "content": {"stage_one": {"a": 1}}}
        result = ProcessingResult.success(data=[item], source_guid="guid_first")

        context = ProcessingContext(
            agent_config={"agent_type": "stage_one"},
            agent_name="stage_one",
            mode=RunMode.ONLINE,
            is_first_stage=True,
            parent_records=[parent],
        )
        enriched = LineageEnricher().enrich(result, context)

        enriched_item = enriched.data[0]
        assert enriched_item["lineage"] == [enriched_item["node_id"]]

    def test_per_item_parent_lookup_resolves_correct_parent_for_each_item(self):
        """Per-item lookups (source_guid is None at result level) must pick the right parent for each output."""
        parents = [
            {"source_guid": f"guid_{i}", "node_id": f"n_{i}", "lineage": [f"n_{i}"]}
            for i in range(5)
        ]
        items = [{"source_guid": f"guid_{i}", "content": {"x": {}}} for i in range(5)]
        result = ProcessingResult.success(data=items, source_guid=None)

        context = _make_context(parent_records=parents)
        enriched = LineageEnricher().enrich(result, context)

        for i, item in enumerate(enriched.data):
            assert item["lineage"][0] == f"n_{i}", (
                f"Item {i} resolved to wrong parent: {item['lineage']}"
            )
            assert item["lineage"][-1] == item["node_id"]


class TestBatchContextAdapterParentRecords:
    """Batch path populates parent_records symmetrically with the online path."""

    def test_batch_adapter_defaults_parent_records_to_empty(self):
        """No explicit parent_records → empty; batch relies on current_item for parent lookup."""
        from agent_actions.processing.batch_context_adapter import BatchContextAdapter

        original_row = {
            "source_guid": "guid_b",
            "node_id": "stage_one_b",
            "lineage": ["stage_one_b"],
        }
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={"agent_type": "stage_two", "dependencies": ["stage_one"]},
            original_row=original_row,
            record_index=0,
        )
        assert ctx.parent_records == []
        assert ctx.current_item is original_row

    def test_batch_adapter_accepts_explicit_parent_records(self):
        """Caller can pass an explicit list (overrides default)."""
        from agent_actions.processing.batch_context_adapter import BatchContextAdapter

        original_row = {"source_guid": "guid_b1"}
        explicit_parents = [
            {"source_guid": "guid_b1", "node_id": "p1", "lineage": ["p1"]},
            {"source_guid": "guid_b2", "node_id": "p2", "lineage": ["p2"]},
        ]
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={"agent_type": "stage_two", "dependencies": ["stage_one"]},
            original_row=original_row,
            record_index=0,
            parent_records=explicit_parents,
        )
        assert ctx.parent_records == explicit_parents

    def test_batch_adapter_empty_when_no_original_row(self):
        """No original_row → empty parent_records, not [None]."""
        from agent_actions.processing.batch_context_adapter import BatchContextAdapter

        ctx = BatchContextAdapter.to_processing_context(
            agent_config={"agent_type": "stage_one"},
            original_row={},  # falsy
            record_index=0,
        )
        assert ctx.parent_records == []

    def test_batch_adapter_seed_record_keeps_current_item_but_no_parents(self):
        """Raw seed input still flows through as current_item; parent_records stays empty."""
        from agent_actions.processing.batch_context_adapter import BatchContextAdapter

        seed = {"source_guid": "seed_1", "page_content": "raw text"}
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={"agent_type": "stage_one"},
            original_row=seed,
            record_index=0,
        )
        assert ctx.parent_records == []
        assert ctx.current_item is seed


class TestGetParentItemDirect:
    """Direct unit tests for LineageEnricher._get_parent_item lookup precedence."""

    def _ctx(
        self,
        is_first_stage: bool = False,
        current_item: dict | None = None,
        parent_records: list[dict] | None = None,
        source_data: list[dict] | None = None,
    ) -> ProcessingContext:
        return ProcessingContext(
            agent_config={"agent_type": "x"},
            agent_name="x",
            mode=RunMode.ONLINE,
            is_first_stage=is_first_stage,
            current_item=current_item,
            parent_records=parent_records or [],
            source_data=source_data or [],
        )

    def test_returns_none_when_first_stage(self):
        ctx = self._ctx(
            is_first_stage=True,
            parent_records=[{"source_guid": "g", "node_id": "n"}],
        )
        assert LineageEnricher()._get_parent_item("g", ctx) is None

    def test_returns_none_when_source_guid_missing(self):
        ctx = self._ctx(parent_records=[{"source_guid": "g", "node_id": "n"}])
        assert LineageEnricher()._get_parent_item(None, ctx) is None

    def test_current_item_wins_over_parent_records(self):
        current = {"source_guid": "g", "node_id": "from_current"}
        parents = [{"source_guid": "g", "node_id": "from_parents"}]
        ctx = self._ctx(current_item=current, parent_records=parents)
        assert LineageEnricher()._get_parent_item("g", ctx)["node_id"] == "from_current"

    def test_current_item_skipped_when_source_guid_mismatches(self):
        """Misconfigured strategy: current_item.source_guid != requested → fall through."""
        current = {"source_guid": "wrong_guid", "node_id": "stale"}
        parents = [{"source_guid": "g", "node_id": "correct_parent", "lineage": ["correct_parent"]}]
        ctx = self._ctx(current_item=current, parent_records=parents)
        assert LineageEnricher()._get_parent_item("g", ctx)["node_id"] == "correct_parent"

    def test_current_item_used_when_source_guid_is_none(self):
        """A current_item without source_guid is treated as the explicit parent for any lookup."""
        current = {"node_id": "from_current"}  # no source_guid
        parents = [{"source_guid": "g", "node_id": "from_parents"}]
        ctx = self._ctx(current_item=current, parent_records=parents)
        assert LineageEnricher()._get_parent_item("g", ctx)["node_id"] == "from_current"

    def test_parent_index_hit_returned(self):
        target = {"source_guid": "g", "node_id": "n"}
        parents = [target, {"source_guid": "other", "node_id": "o"}]
        index = {p["source_guid"]: p for p in parents}
        ctx = self._ctx(parent_records=parents)
        assert LineageEnricher()._get_parent_item("g", ctx, parent_index=index) is target

    def test_parent_index_miss_falls_through_to_source_data(self):
        """Miss in parent_records falls through to source_data so FILE-mode lookups still resolve."""
        parents = [{"source_guid": "other", "node_id": "o"}]
        index = {p["source_guid"]: p for p in parents}
        source_match = {"source_guid": "g", "node_id": "from_source"}
        ctx = self._ctx(parent_records=parents, source_data=[source_match])
        source_index = {source_match["source_guid"]: source_match}
        result = LineageEnricher()._get_parent_item(
            "g", ctx, source_index=source_index, parent_index=index
        )
        assert result is source_match

    def test_linear_scan_when_parent_index_omitted(self):
        target = {"source_guid": "g", "node_id": "n"}
        ctx = self._ctx(parent_records=[target])
        assert LineageEnricher()._get_parent_item("g", ctx) is target

    def test_falls_through_to_source_index_when_parents_empty(self):
        seed = [{"source_guid": "g", "node_id": "from_seed"}]
        source_index = {p["source_guid"]: p for p in seed}
        ctx = self._ctx(parent_records=[], source_data=seed)
        result = LineageEnricher()._get_parent_item("g", ctx, source_index=source_index)
        assert result is seed[0]


class TestSourceMappingParentFallback:
    """When source_mapping pins a lineage-less record, parent_index recovers the real parent."""

    def test_one_to_one_source_mapping_recovers_lineage_from_parent_records(self):
        # source_data has the raw seed (no lineage) at index 0
        seed = {"source_guid": "g", "page_content": "raw"}
        # parent_records has the lineage-bearing record for the same guid
        lineage_parent = {
            "source_guid": "g",
            "node_id": "stage_one",
            "lineage": ["stage_one"],
        }

        item = {"source_guid": "g", "content": {"x": {}}}
        result = ProcessingResult.success(data=[item], source_guid=None)
        result.source_mapping = {0: 0}

        context = ProcessingContext(
            agent_config={"agent_type": "stage_two"},
            agent_name="stage_two",
            mode=RunMode.ONLINE,
            is_first_stage=False,
            source_data=[seed],
            parent_records=[lineage_parent],
        )
        enriched = LineageEnricher().enrich(result, context)
        enriched_item = enriched.data[0]

        assert enriched_item["lineage"][0] == "stage_one"
        assert enriched_item["lineage"][-1] == enriched_item["node_id"]

    def test_many_to_one_source_mapping_recovers_lineage_for_each_source(self):
        seed_a = {"source_guid": "g_a", "page_content": "raw a"}
        seed_b = {"source_guid": "g_b", "page_content": "raw b"}
        parent_a = {"source_guid": "g_a", "node_id": "p_a", "lineage": ["p_a"]}
        parent_b = {"source_guid": "g_b", "node_id": "p_b", "lineage": ["p_b"]}

        item = {"source_guid": "g_a", "content": {"x": {}}}
        result = ProcessingResult.success(data=[item], source_guid=None)
        result.source_mapping = {0: [0, 1]}

        context = ProcessingContext(
            agent_config={"agent_type": "stage_two"},
            agent_name="stage_two",
            mode=RunMode.ONLINE,
            is_first_stage=False,
            source_data=[seed_a, seed_b],
            parent_records=[parent_a, parent_b],
        )
        enriched = LineageEnricher().enrich(result, context)
        enriched_item = enriched.data[0]

        assert "p_a" in enriched_item["lineage"]
        assert enriched_item["lineage"][-1] == enriched_item["node_id"]
