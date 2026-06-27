"""Regression test for VIOL-0016: downstream lineage must extend the chain.

The bug: `pipeline.py` overwrote `context.source_data` with raw seed records
from storage (no `lineage`/`node_id`), then `LineageEnricher` used those as
parent_item. `LineageBuilder.add_unified_lineage` fell through to
``obj["lineage"] = [node_id]`` because ``"lineage" not in parent_item``.

The fix: ``ProcessingContext.parent_records`` carries the previous-stage
output (with lineage). ``LineageEnricher._get_parent_item`` prefers it over
``source_data``.
"""

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
        """No parent_records → fall back to source_data behavior (legacy path)."""
        # Source data with full lineage (simulating FILE-mode unified.py:113 path).
        legacy_parent_node_id = "stage_one_legacy"
        source_data_with_lineage = [
            {
                "source_guid": "guid_legacy",
                "node_id": legacy_parent_node_id,
                "lineage": [legacy_parent_node_id],
            }
        ]
        item = {"source_guid": "guid_legacy", "content": {"stage_two": {"y": 2}}}
        result = ProcessingResult.success(data=[item], source_guid="guid_legacy")

        context = _make_context(parent_records=[], source_data=source_data_with_lineage)
        enriched = LineageEnricher().enrich(result, context)

        enriched_item = enriched.data[0]
        assert len(enriched_item["lineage"]) == 2
        assert enriched_item["lineage"][0] == legacy_parent_node_id

    def test_raw_seed_only_produces_self_lineage(self):
        """Sanity: with neither parent_records nor lineage-bearing source_data, lineage is self-only.

        This pins the pre-fix behavior so it's clear when the new code is doing the work.
        """
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
