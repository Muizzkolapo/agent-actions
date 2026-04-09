"""Deterministic integration tests for record lineage integrity.

These tests verify that lineage metadata (node_id, lineage, parent_target_id,
root_target_id, lineage_sources, source_guid) is correctly built and propagated
across every processing pattern in the pipeline.
"""

import logging
import uuid

from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.utils.correlation.version_id import VersionIdGenerator


def _make_context(
    source_data,
    is_first_stage=False,
    action_name="test_action",
    current_item=None,
    record_index=0,
):
    """Create a ProcessingContext with the given source_data."""
    return ProcessingContext(
        agent_config={"agent_type": action_name},
        agent_name=action_name,
        is_first_stage=is_first_stage,
        source_data=source_data,
        current_item=current_item,
        record_index=record_index,
    )


def _make_source_item(source_guid, node_id, lineage=None, target_id=None, root_target_id=None):
    """Create a source data item with lineage and ancestry chain."""
    item = {
        "source_guid": source_guid,
        "node_id": node_id,
        "lineage": lineage if lineage is not None else [node_id],
        "content": {"data": f"from_{node_id}"},
    }
    if target_id is not None:
        item["target_id"] = target_id
    if root_target_id is not None:
        item["root_target_id"] = root_target_id
    return item


def _uuid() -> str:
    return str(uuid.uuid4())


class TestLineage1To1:
    """Single record flows through sequential actions."""

    def test_first_stage_record_gets_lineage_with_single_node(self):
        """First-stage record: lineage = [node_id], no parent_target_id."""
        guid = _uuid()
        result = ProcessingResult.success(
            data=[{"content": {"text": "hello"}, "source_guid": guid}],
            source_guid=guid,
        )
        context = _make_context(
            source_data=[],
            is_first_stage=True,
            action_name="extract",
        )

        enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        assert item["node_id"].startswith("extract_")
        assert item["lineage"] == [item["node_id"]]
        assert "parent_target_id" not in item
        assert "root_target_id" not in item

    def test_second_stage_inherits_parent_lineage(self):
        """Second-stage: lineage = [parent_node, current_node], parent_target_id set."""
        guid = _uuid()
        parent_node_id = f"extract_{_uuid()}"
        parent_target_id = _uuid()

        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node_id,
            lineage=[parent_node_id],
            target_id=parent_target_id,
        )

        result = ProcessingResult.success(
            data=[{"content": {"text": "transformed"}, "source_guid": guid}],
            source_guid=guid,
        )
        context = _make_context(
            source_data=[parent_item],
            is_first_stage=False,
            action_name="transform",
        )

        enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        assert item["node_id"].startswith("transform_")
        assert item["lineage"] == [parent_node_id, item["node_id"]]
        assert item["parent_target_id"] == parent_target_id
        assert item["root_target_id"] == parent_target_id

    def test_three_stage_chain_builds_complete_lineage(self):
        """A -> B -> C: lineage grows by one node_id per stage."""
        guid = _uuid()

        # Stage 1: extract (first stage)
        result_a = ProcessingResult.success(
            data=[{"content": {"raw": "data"}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx_a = _make_context(source_data=[], is_first_stage=True, action_name="extract")
        enriched_a = LineageEnricher().enrich(result_a, ctx_a)
        item_a = enriched_a.data[0]
        node_a = item_a["node_id"]
        # Give item_a a target_id for ancestry chain
        target_a = _uuid()
        item_a["target_id"] = target_a

        # Stage 2: transform
        result_b = ProcessingResult.success(
            data=[{"content": {"processed": True}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx_b = _make_context(source_data=[item_a], is_first_stage=False, action_name="transform")
        enriched_b = LineageEnricher().enrich(result_b, ctx_b)
        item_b = enriched_b.data[0]
        node_b = item_b["node_id"]
        target_b = _uuid()
        item_b["target_id"] = target_b

        # Stage 3: summarize
        result_c = ProcessingResult.success(
            data=[{"content": {"summary": "done"}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx_c = _make_context(source_data=[item_b], is_first_stage=False, action_name="summarize")
        enriched_c = LineageEnricher().enrich(result_c, ctx_c)
        item_c = enriched_c.data[0]
        node_c = item_c["node_id"]

        assert item_c["lineage"] == [node_a, node_b, node_c]
        assert len(item_c["lineage"]) == 3
        assert item_c["parent_target_id"] == target_b
        assert item_c["root_target_id"] == target_a

    def test_root_target_id_propagates_through_chain(self):
        """root_target_id set at stage 1, propagated unchanged through stages 2+."""
        guid = _uuid()
        root_tid = _uuid()
        parent_node = f"extract_{_uuid()}"
        parent_tid = _uuid()

        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node,
            lineage=[parent_node],
            target_id=parent_tid,
            root_target_id=root_tid,
        )

        result = ProcessingResult.success(
            data=[{"content": {"val": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        context = _make_context(
            source_data=[parent_item], is_first_stage=False, action_name="transform"
        )

        enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        # root_target_id should be the original root, not the parent's target_id
        assert item["root_target_id"] == root_tid
        assert item["parent_target_id"] == parent_tid

    def test_source_guid_preserved_through_chain(self):
        """source_guid from input preserved at every stage."""
        guid = _uuid()
        parent_node = f"extract_{_uuid()}"

        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node,
            target_id=_uuid(),
        )

        result = ProcessingResult.success(
            data=[{"content": {"val": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        context = _make_context(
            source_data=[parent_item], is_first_stage=False, action_name="transform"
        )

        enriched = LineageEnricher().enrich(result, context)

        assert enriched.data[0]["source_guid"] == guid
        assert enriched.source_guid == guid


class TestLineage1ToN:
    """One input record splits into multiple output records."""

    def test_split_records_get_unique_node_ids(self):
        """1 input -> 3 outputs: each gets node_id_{0,1,2}."""
        guid = _uuid()
        result = ProcessingResult.success(
            data=[
                {"content": {"chunk": 0}, "source_guid": guid},
                {"content": {"chunk": 1}, "source_guid": guid},
                {"content": {"chunk": 2}, "source_guid": guid},
            ],
            source_guid=guid,
        )
        context = _make_context(source_data=[], is_first_stage=True, action_name="split")

        enriched = LineageEnricher().enrich(result, context)

        node_ids = [item["node_id"] for item in enriched.data]
        assert len(set(node_ids)) == 3
        # Each should end with _0, _1, _2
        for i, item in enumerate(enriched.data):
            assert item["node_id"].endswith(f"_{i}")
            assert item["node_id"].startswith("split_")

    def test_split_records_share_parent_target_id(self):
        """All split children point to same parent_target_id (the input's target_id)."""
        guid = _uuid()
        parent_node = f"extract_{_uuid()}"
        parent_tid = _uuid()

        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node,
            target_id=parent_tid,
        )

        result = ProcessingResult.success(
            data=[{"content": {"chunk": i}, "source_guid": guid} for i in range(3)],
            source_guid=guid,
        )
        context = _make_context(
            source_data=[parent_item], is_first_stage=False, action_name="split"
        )

        enriched = LineageEnricher().enrich(result, context)

        for item in enriched.data:
            assert item["parent_target_id"] == parent_tid

    def test_split_records_share_root_target_id(self):
        """All split children share same root_target_id."""
        guid = _uuid()
        root_tid = _uuid()
        parent_node = f"extract_{_uuid()}"
        parent_tid = _uuid()

        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node,
            target_id=parent_tid,
            root_target_id=root_tid,
        )

        result = ProcessingResult.success(
            data=[{"content": {"chunk": i}, "source_guid": guid} for i in range(3)],
            source_guid=guid,
        )
        context = _make_context(
            source_data=[parent_item], is_first_stage=False, action_name="split"
        )

        enriched = LineageEnricher().enrich(result, context)

        for item in enriched.data:
            assert item["root_target_id"] == root_tid

    def test_split_records_share_source_guid(self):
        """All split children preserve the input's source_guid."""
        guid = _uuid()
        result = ProcessingResult.success(
            data=[{"content": {"chunk": i}, "source_guid": guid} for i in range(3)],
            source_guid=guid,
        )
        context = _make_context(source_data=[], is_first_stage=True, action_name="split")

        enriched = LineageEnricher().enrich(result, context)

        for item in enriched.data:
            assert item["source_guid"] == guid

    def test_split_records_have_independent_target_ids(self):
        """Each split child gets its own unique target_id."""
        guid = _uuid()
        # Pre-assign unique target_ids to output items
        target_ids = [_uuid() for _ in range(3)]
        result = ProcessingResult.success(
            data=[
                {"content": {"chunk": i}, "source_guid": guid, "target_id": target_ids[i]}
                for i in range(3)
            ],
            source_guid=guid,
        )
        context = _make_context(source_data=[], is_first_stage=True, action_name="split")

        enriched = LineageEnricher().enrich(result, context)

        result_target_ids = [item["target_id"] for item in enriched.data]
        assert len(set(result_target_ids)) == 3
        for i, item in enumerate(enriched.data):
            assert item["target_id"] == target_ids[i]

    def test_downstream_of_split_gets_correct_parent(self):
        """After split, a subsequent action on each child links to that child, not siblings."""
        guid = _uuid()
        parent_node = f"extract_{_uuid()}"
        parent_tid = _uuid()

        # First: split produces 3 children
        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node,
            target_id=parent_tid,
        )
        split_result = ProcessingResult.success(
            data=[{"content": {"chunk": i}, "source_guid": guid} for i in range(3)],
            source_guid=guid,
        )
        split_ctx = _make_context(
            source_data=[parent_item], is_first_stage=False, action_name="split"
        )
        split_enriched = LineageEnricher().enrich(split_result, split_ctx)

        # Give each split child a target_id
        child_tids = []
        for item in split_enriched.data:
            tid = _uuid()
            item["target_id"] = tid
            child_tids.append(tid)

        # Process child[1] through downstream action using source_mapping
        child_1 = split_enriched.data[1]
        downstream_result = ProcessingResult.success(
            data=[{"content": {"refined": True}, "source_guid": guid}],
            source_guid=guid,
        )
        downstream_ctx = _make_context(
            source_data=[child_1],
            is_first_stage=False,
            action_name="refine",
        )

        downstream_enriched = LineageEnricher().enrich(downstream_result, downstream_ctx)
        downstream_item = downstream_enriched.data[0]

        # Should link to child_1, not child_0 or child_2
        assert downstream_item["parent_target_id"] == child_tids[1]
        assert child_1["node_id"] in downstream_item["lineage"]


class TestLineageNTo1Merge:
    """Multiple input records merge into fewer output records."""

    def test_file_mode_many_to_one_sets_lineage_sources(self):
        """3 inputs merged via source_mapping={0: [0,1,2]}: output has lineage_sources with all 3 parent node_ids."""
        source_items = [
            _make_source_item(f"guid_{i}", f"flatten_{_uuid()}", target_id=_uuid())
            for i in range(3)
        ]
        source_node_ids = [item["node_id"] for item in source_items]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"merged": True}}],
            source_guid=None,
            source_mapping={0: [0, 1, 2]},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="merge_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        assert "lineage_sources" in item
        assert len(item["lineage_sources"]) == 3
        for nid in source_node_ids:
            assert nid in item["lineage_sources"]

    def test_file_mode_many_to_one_lineage_uses_first_source(self):
        """Merged output's lineage chain is built from first source item."""
        first_node = f"extract_{_uuid()}"
        source_items = [
            _make_source_item("guid_0", first_node, target_id=_uuid()),
            _make_source_item("guid_1", f"extract_{_uuid()}", target_id=_uuid()),
            _make_source_item("guid_2", f"extract_{_uuid()}", target_id=_uuid()),
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"merged": True}}],
            source_guid=None,
            source_mapping={0: [0, 1, 2]},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="merge_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        # Lineage should be built from first source's lineage + current node
        assert item["lineage"][0] == first_node
        assert item["lineage"][-1] == item["node_id"]

    def test_file_mode_many_to_one_ancestry_from_first_source(self):
        """parent_target_id and root_target_id propagated from first source."""
        first_tid = _uuid()
        first_root_tid = _uuid()
        source_items = [
            _make_source_item(
                "guid_0",
                f"extract_{_uuid()}",
                target_id=first_tid,
                root_target_id=first_root_tid,
            ),
            _make_source_item("guid_1", f"extract_{_uuid()}", target_id=_uuid()),
            _make_source_item("guid_2", f"extract_{_uuid()}", target_id=_uuid()),
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"merged": True}}],
            source_guid=None,
            source_mapping={0: [0, 1, 2]},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="merge_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        assert item["parent_target_id"] == first_tid
        assert item["root_target_id"] == first_root_tid


class TestLineageNToMDedup:
    """FILE-mode dedup: N inputs -> M outputs with source_mapping."""

    def test_dedup_with_shared_source_guid_produces_distinct_lineage(self):
        """5 inputs sharing source_guid, source_mapping={0:0, 1:1, 2:2}: each output gets distinct parent lineage.
        This is the bug that PR #220 fixed -- regression guard."""
        shared_guid = "shared-dedup-guid"
        source_items = [
            _make_source_item(
                shared_guid,
                f"flatten_{_uuid()}",
                target_id=_uuid(),
            )
            for _ in range(5)
        ]

        # 3 outputs, each mapped to a different input
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"deduped": i}, "source_guid": shared_guid} for i in range(3)],
            source_guid=None,
            source_mapping={0: 0, 1: 1, 2: 2},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="dedup_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        # Each output should trace to its specific input, not all to input[0]
        for i in range(3):
            item = enriched.data[i]
            expected_parent_node = source_items[i]["node_id"]
            assert expected_parent_node in item["lineage"], (
                f"Output {i} lineage should include parent {expected_parent_node}, "
                f"got {item['lineage']}"
            )
            assert item["parent_target_id"] == source_items[i]["target_id"]

    def test_dedup_source_mapping_one_to_one(self):
        """5 inputs -> 3 outputs, source_mapping={0:0, 1:2, 2:4}: each output traces to correct input."""
        guids = [_uuid() for _ in range(5)]
        source_items = [
            _make_source_item(
                guids[i],
                f"flatten_{_uuid()}",
                target_id=_uuid(),
            )
            for i in range(5)
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"content": {"deduped": 0}, "source_guid": guids[0]},
                {"content": {"deduped": 1}, "source_guid": guids[2]},
                {"content": {"deduped": 2}, "source_guid": guids[4]},
            ],
            source_guid=None,
            source_mapping={0: 0, 1: 2, 2: 4},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="dedup_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        # Output 0 -> input 0
        assert source_items[0]["node_id"] in enriched.data[0]["lineage"]
        assert enriched.data[0]["parent_target_id"] == source_items[0]["target_id"]
        # Output 1 -> input 2
        assert source_items[2]["node_id"] in enriched.data[1]["lineage"]
        assert enriched.data[1]["parent_target_id"] == source_items[2]["target_id"]
        # Output 2 -> input 4
        assert source_items[4]["node_id"] in enriched.data[2]["lineage"]
        assert enriched.data[2]["parent_target_id"] == source_items[4]["target_id"]

    def test_dedup_without_source_mapping_falls_back_to_guid(self):
        """FileUDFResult without source_mapping: lineage resolved by source_guid scan (backward compat)."""
        guid_a = _uuid()
        guid_b = _uuid()
        node_a = f"flatten_{_uuid()}"
        node_b = f"flatten_{_uuid()}"

        source_items = [
            _make_source_item(guid_a, node_a, target_id=_uuid()),
            _make_source_item(guid_b, node_b, target_id=_uuid()),
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"content": {"val": 1}, "source_guid": guid_a},
                {"content": {"val": 2}, "source_guid": guid_b},
            ],
            source_guid=None,
            source_mapping=None,  # No mapping -> fallback to source_guid scan
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="dedup_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        assert node_a in enriched.data[0]["lineage"]
        assert node_b in enriched.data[1]["lineage"]

    def test_dedup_output_ids_are_unique(self):
        """All dedup outputs have unique target_id and unique node_id."""
        shared_guid = "shared-guid"
        source_items = [
            _make_source_item(shared_guid, f"flatten_{_uuid()}", target_id=_uuid())
            for _ in range(5)
        ]

        target_ids = [_uuid() for _ in range(3)]
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"content": {"val": i}, "source_guid": shared_guid, "target_id": target_ids[i]}
                for i in range(3)
            ],
            source_guid=None,
            source_mapping={0: 0, 1: 1, 2: 2},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="dedup_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        node_ids = [item["node_id"] for item in enriched.data]
        result_target_ids = [item["target_id"] for item in enriched.data]
        assert len(set(node_ids)) == 3
        assert len(set(result_target_ids)) == 3


class TestLineageFileMode:
    """FILE-mode tool processing lineage integrity."""

    def test_file_mode_preserves_source_guid_per_item(self):
        """Each output item preserves source_guid from its input."""
        guid_a = _uuid()
        guid_b = _uuid()
        source_items = [
            _make_source_item(guid_a, f"extract_{_uuid()}", target_id=_uuid()),
            _make_source_item(guid_b, f"extract_{_uuid()}", target_id=_uuid()),
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"content": {"out": 0}, "source_guid": guid_a},
                {"content": {"out": 1}, "source_guid": guid_b},
            ],
            source_guid=None,
            source_mapping={0: 0, 1: 1},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="file_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        assert enriched.data[0]["source_guid"] == guid_a
        assert enriched.data[1]["source_guid"] == guid_b

    def test_file_mode_node_ids_indexed(self):
        """Multiple outputs get node_id_{0}, node_id_{1}, etc."""
        source_items = [
            _make_source_item(_uuid(), f"extract_{_uuid()}", target_id=_uuid()) for _ in range(3)
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"out": i}} for i in range(3)],
            source_guid=None,
            source_mapping={0: 0, 1: 1, 2: 2},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="file_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        for i, item in enumerate(enriched.data):
            assert item["node_id"].endswith(f"_{i}")

    def test_file_mode_single_output_no_index_suffix(self):
        """Single output gets node_id without _{0} suffix."""
        source_item = _make_source_item(_uuid(), f"extract_{_uuid()}", target_id=_uuid())

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"out": 0}}],
            source_guid=None,
            source_mapping={0: 0},
        )
        context = _make_context(
            source_data=[source_item],
            is_first_stage=False,
            action_name="file_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        node_id = enriched.data[0]["node_id"]
        assert node_id.startswith("file_tool_")
        # Single output: no _0 suffix appended after the UUID
        # The node_id is just "file_tool_{uuid}" without an extra _0
        assert not node_id.endswith("_0")

    def test_file_mode_parent_lookup_uses_correct_input(self):
        """With 3 different source_guids, each output links to its own parent."""
        guids = [_uuid() for _ in range(3)]
        source_items = [
            _make_source_item(guids[i], f"extract_{_uuid()}", target_id=_uuid()) for i in range(3)
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"out": i}, "source_guid": guids[i]} for i in range(3)],
            source_guid=None,
            source_mapping={0: 0, 1: 1, 2: 2},
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="file_tool",
        )

        enriched = LineageEnricher().enrich(result, context)

        for i in range(3):
            assert enriched.data[i]["parent_target_id"] == source_items[i]["target_id"]
            assert source_items[i]["node_id"] in enriched.data[i]["lineage"]

    def test_file_mode_empty_output_returns_failed(self):
        """Empty tool output from non-empty input returns FAILED status."""
        result = ProcessingResult.failed(
            error="Tool returned empty output",
            source_guid=_uuid(),
        )

        assert result.status == ProcessingStatus.FAILED
        assert result.data == []
        assert result.error == "Tool returned empty output"


class TestLineageVersionParallel:
    """Version/parallel actions: same input processed by multiple agents."""

    def test_version_correlation_id_deterministic(self):
        """Same session_id + version_base_name + source_guid -> same correlation_id across calls."""
        session_id = _uuid()
        base_name = "voter"
        guid = _uuid()

        VersionIdGenerator.clear()
        cid_1 = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid=guid,
            version_base_name=base_name,
            workflow_session_id=session_id,
        )
        cid_2 = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid=guid,
            version_base_name=base_name,
            workflow_session_id=session_id,
        )

        assert cid_1 == cid_2
        assert cid_1.startswith("corr_")
        assert len(cid_1) == 21  # "corr_" + 16 hex chars

    def test_version_correlation_id_differs_across_versions(self):
        """Different version_base_name -> different correlation_id for same record."""
        session_id = _uuid()
        guid = _uuid()

        VersionIdGenerator.clear()
        cid_voter_a = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid=guid,
            version_base_name="voter_a",
            workflow_session_id=session_id,
        )
        cid_voter_b = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid=guid,
            version_base_name="voter_b",
            workflow_session_id=session_id,
        )

        assert cid_voter_a != cid_voter_b
        assert cid_voter_a.startswith("corr_")
        assert cid_voter_b.startswith("corr_")

    def test_parallel_outputs_share_parent_target_id(self):
        """3 voters on same input: all outputs have same parent_target_id."""
        guid = _uuid()
        parent_node = f"extract_{_uuid()}"
        parent_tid = _uuid()

        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node,
            target_id=parent_tid,
        )

        # Simulate 3 parallel voters processing the same input
        parent_target_ids = []
        for voter_name in ["voter_a", "voter_b", "voter_c"]:
            result = ProcessingResult.success(
                data=[{"content": {"vote": voter_name}, "source_guid": guid}],
                source_guid=guid,
            )
            context = _make_context(
                source_data=[parent_item],
                is_first_stage=False,
                action_name=voter_name,
            )
            enriched = LineageEnricher().enrich(result, context)
            parent_target_ids.append(enriched.data[0]["parent_target_id"])

        assert all(tid == parent_tid for tid in parent_target_ids)

    def test_parallel_outputs_have_unique_target_ids(self):
        """Each voter output gets its own target_id."""
        guid = _uuid()
        parent_node = f"extract_{_uuid()}"
        parent_tid = _uuid()

        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node,
            target_id=parent_tid,
        )

        target_ids = [_uuid(), _uuid(), _uuid()]
        for i, voter_name in enumerate(["voter_a", "voter_b", "voter_c"]):
            result = ProcessingResult.success(
                data=[
                    {
                        "content": {"vote": voter_name},
                        "source_guid": guid,
                        "target_id": target_ids[i],
                    }
                ],
                source_guid=guid,
            )
            context = _make_context(
                source_data=[parent_item],
                is_first_stage=False,
                action_name=voter_name,
            )
            enriched = LineageEnricher().enrich(result, context)

            assert enriched.data[0]["target_id"] == target_ids[i]

        assert len(set(target_ids)) == 3

    def test_parallel_outputs_have_independent_lineage(self):
        """Each voter's lineage chain includes its own action's node_id."""
        guid = _uuid()
        parent_node = f"extract_{_uuid()}"
        parent_tid = _uuid()

        parent_item = _make_source_item(
            source_guid=guid,
            node_id=parent_node,
            target_id=parent_tid,
        )

        voter_node_ids = []
        for voter_name in ["voter_a", "voter_b", "voter_c"]:
            result = ProcessingResult.success(
                data=[{"content": {"vote": voter_name}, "source_guid": guid}],
                source_guid=guid,
            )
            context = _make_context(
                source_data=[parent_item],
                is_first_stage=False,
                action_name=voter_name,
            )
            enriched = LineageEnricher().enrich(result, context)
            item = enriched.data[0]

            # Each voter's node_id should start with voter name
            assert item["node_id"].startswith(f"{voter_name}_")
            # Lineage should include parent node + this voter's node
            assert item["lineage"] == [parent_node, item["node_id"]]
            voter_node_ids.append(item["node_id"])

        # All voter node_ids should be unique
        assert len(set(voter_node_ids)) == 3


class TestLineageEdgeCases:
    """Edge cases and error handling."""

    def test_missing_parent_item_produces_root_lineage(self):
        """No parent -> lineage = [node_id], no parent_target_id."""
        guid = _uuid()
        result = ProcessingResult.success(
            data=[{"content": {"text": "orphan"}, "source_guid": guid}],
            source_guid=guid,
        )
        # is_first_stage=True means no parent lookup
        context = _make_context(
            source_data=[],
            is_first_stage=True,
            action_name="extract",
        )

        enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        assert item["lineage"] == [item["node_id"]]
        assert "parent_target_id" not in item
        assert "root_target_id" not in item

    def test_filtered_result_bypasses_enrichment(self):
        """FILTERED status: enrichment skipped, no lineage fields added."""
        result = ProcessingResult.filtered(source_guid=_uuid())

        context = _make_context(
            source_data=[],
            is_first_stage=True,
            action_name="extract",
        )

        enriched = LineageEnricher().enrich(result, context)

        assert enriched.status == ProcessingStatus.FILTERED
        assert enriched.data == []
        assert enriched.node_id is None

    def test_out_of_bounds_source_mapping_logs_warning(self, caplog):
        """source_mapping pointing beyond source_data: warning logged, parent_item=None."""
        source_items = [
            _make_source_item(_uuid(), f"extract_{_uuid()}", target_id=_uuid()),
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"val": 1}}],
            source_guid=None,
            source_mapping={0: 99},  # Out of bounds
        )
        context = _make_context(
            source_data=source_items,
            is_first_stage=False,
            action_name="tool_action",
        )

        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.enrichment"):
            enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        # Should still get a lineage (root lineage since parent is None)
        assert item["lineage"] == [item["node_id"]]
        assert "parent_target_id" not in item

        # Warning should have been logged
        assert any("out of bounds" in record.message for record in caplog.records)

    def test_source_guid_empty_string_treated_as_none(self):
        """Empty string source_guid normalized to None."""
        result = ProcessingResult.success(
            data=[{"content": {"text": "data"}, "source_guid": ""}],
            source_guid="",
        )

        parent_item = _make_source_item(
            source_guid="valid-guid",
            node_id=f"extract_{_uuid()}",
            target_id=_uuid(),
        )

        context = _make_context(
            source_data=[parent_item],
            is_first_stage=False,
            action_name="transform",
        )

        enriched = LineageEnricher().enrich(result, context)

        item = enriched.data[0]
        # Empty string source_guid should result in _get_parent_item returning None
        # (treated like no source_guid), so lineage is root-level
        assert item["lineage"] == [item["node_id"]]
        assert "parent_target_id" not in item
