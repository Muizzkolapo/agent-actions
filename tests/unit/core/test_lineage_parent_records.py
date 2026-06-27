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

    def test_parent_index_o1_lookup(self):
        """Per-item lookup uses an O(1) parent_index, not a linear scan.

        With 1000 parents, repeated lookups must complete in well under
        a second. A linear scan would be O(N*M) and become observable.
        """
        import time

        N = 1000
        parents = [
            {
                "source_guid": f"guid_{i}",
                "node_id": f"stage_one_{i}",
                "lineage": [f"stage_one_{i}"],
            }
            for i in range(N)
        ]
        # 100 outputs, each mapped to a different parent via per-item source_guid
        items = [{"source_guid": f"guid_{i}", "content": {"stage_two": {}}} for i in range(100)]
        result = ProcessingResult.success(
            data=items,
            source_guid=None,  # forces per-item parent lookup
        )

        context = _make_context(parent_records=parents)
        start = time.perf_counter()
        enriched = LineageEnricher().enrich(result, context)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Parent lookup took {elapsed:.3f}s — index may not be in use"
        for i, item in enumerate(enriched.data):
            assert item["lineage"][0] == f"stage_one_{i}", (
                f"Item {i} lineage didn't extend correct parent: {item['lineage']}"
            )


class TestBatchContextAdapterParentRecords:
    """Batch path populates parent_records symmetrically with the online path."""

    def test_batch_adapter_defaults_parent_records_to_original_row(self):
        """When no parent_records passed, adapter defaults to [original_row]."""
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
        assert ctx.parent_records == [original_row]
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
