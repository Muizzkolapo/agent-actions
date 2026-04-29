"""Comprehensive lineage & node metadata audit tests.

Tests lineage consistency across:
- LLM × TOOL × HITL action types
- RECORD × FILE granularity
- First-stage (no parent) vs subsequent-stage
- Fan-in, Diamond, Map-Reduce patterns
- source_mapping index resolution vs source_guid scan
- Ancestry chain propagation (parent_target_id, root_target_id)

Audit spec: specs/new/026-lineage-node-metadata-audit.md
"""

import re
import uuid

from agent_actions.processing.enrichment import (
    EnrichmentPipeline,
    LineageEnricher,
    RequiredFieldsEnricher,
)
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)

# Valid node_id pattern: {action_name}_{identifier}
_NODE_ID_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*_[a-zA-Z0-9_-]+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid() -> str:
    return str(uuid.uuid4())


def _make_context(
    source_data,
    is_first_stage=False,
    action_name="test_action",
    current_item=None,
    record_index=0,
):
    """Create a ProcessingContext with the given source_data."""
    return ProcessingContext(
        agent_config={"agent_type": action_name, "name": action_name},
        agent_name=action_name,
        is_first_stage=is_first_stage,
        source_data=source_data,
        current_item=current_item,
        record_index=record_index,
    )


def _make_source_item(
    source_guid,
    node_id,
    lineage=None,
    target_id=None,
    root_target_id=None,
):
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


def _enrich_lineage(result, context):
    """Run LineageEnricher on a ProcessingResult."""
    return LineageEnricher().enrich(result, context)


def _enrich_full(result, context):
    """Run LineageEnricher + RequiredFieldsEnricher (the two that set metadata fields)."""
    pipeline = EnrichmentPipeline(enrichers=[LineageEnricher(), RequiredFieldsEnricher()])
    return pipeline.enrich(result, context)


# ---------------------------------------------------------------------------
# TestLineageChainIntegrity
# ---------------------------------------------------------------------------


class TestLineageChainIntegrity:
    """Verify lineage chains grow correctly at each stage and never truncate."""

    def test_first_stage_lineage_contains_only_self(self):
        """First-stage: lineage = [node_id], no ancestry fields."""
        guid = _uuid()
        result = ProcessingResult.success(
            data=[{"content": {"text": "hello"}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[], is_first_stage=True, action_name="ingest")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert item["lineage"] == [item["node_id"]]
        assert "parent_target_id" not in item
        assert "root_target_id" not in item

    def test_subsequent_stage_extends_parent_lineage(self):
        """Stage 2: lineage = [parent_node, current_node]."""
        guid = _uuid()
        parent_nid = f"ingest_{_uuid()}"
        parent_tid = _uuid()
        parent = _make_source_item(guid, parent_nid, target_id=parent_tid)

        result = ProcessingResult.success(
            data=[{"content": {"val": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[parent], is_first_stage=False, action_name="transform")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert len(item["lineage"]) == 2
        assert item["lineage"][0] == parent_nid
        assert item["lineage"][1] == item["node_id"]

    def test_lineage_never_truncated_across_four_stages(self):
        """A→B→C→D: lineage grows from 1 to 4 entries, never shrinks."""
        guid = _uuid()
        stages = ["extract", "transform", "enrich", "summarize"]
        prev_item = None
        accumulated_nids = []

        for i, action in enumerate(stages):
            result = ProcessingResult.success(
                data=[{"content": {"stage": i}, "source_guid": guid}],
                source_guid=guid,
            )
            is_first = i == 0
            source_data = [prev_item] if prev_item else []
            ctx = _make_context(
                source_data=source_data, is_first_stage=is_first, action_name=action
            )
            enriched = _enrich_lineage(result, ctx)
            item = enriched.data[0]

            accumulated_nids.append(item["node_id"])
            assert item["lineage"] == accumulated_nids, (
                f"Stage {action}: expected lineage length {len(accumulated_nids)}, "
                f"got {len(item['lineage'])}"
            )

            # Prep for next stage
            item["target_id"] = _uuid()
            if i == 0:
                item["root_target_id"] = item["target_id"]
            prev_item = item

    def test_lineage_format_valid_node_ids_only(self):
        """Every entry in every lineage array matches the {action}_{id} pattern."""
        guid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent = _make_source_item(guid, parent_nid, target_id=_uuid())

        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[parent], is_first_stage=False, action_name="transform")
        enriched = _enrich_lineage(result, ctx)

        for nid in enriched.data[0]["lineage"]:
            assert isinstance(nid, str), f"Lineage entry must be str, got {type(nid)}"
            assert _NODE_ID_PATTERN.match(nid), f"Invalid node_id format: {nid!r}"

    def test_lineage_with_malformed_parent_entries_filtered(self):
        """Invalid entries in parent's lineage are filtered out before extension."""
        guid = _uuid()
        valid_nid = f"extract_{_uuid()}"
        parent = _make_source_item(guid, valid_nid, target_id=_uuid())
        # Inject invalid entries into parent lineage
        parent["lineage"] = [42, "", "no-underscore", valid_nid]

        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[parent], is_first_stage=False, action_name="transform")
        enriched = _enrich_lineage(result, ctx)
        lineage = enriched.data[0]["lineage"]

        # Only valid_nid and current node_id should survive
        assert len(lineage) == 2
        assert lineage[0] == valid_nid
        for nid in lineage:
            assert _NODE_ID_PATTERN.match(nid)


# ---------------------------------------------------------------------------
# TestAncestryFields
# ---------------------------------------------------------------------------


class TestAncestryFields:
    """Verify target_id, parent_target_id, and root_target_id correctness."""

    def test_target_id_unique_per_record(self):
        """Each enriched record gets a unique target_id via RequiredFieldsEnricher."""
        guid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent = _make_source_item(guid, parent_nid, target_id=_uuid())

        result = ProcessingResult.success(
            data=[{"content": {"chunk": i}, "source_guid": guid} for i in range(5)],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[parent], is_first_stage=False, action_name="split")
        enriched = _enrich_full(result, ctx)

        target_ids = [item["target_id"] for item in enriched.data]
        assert len(set(target_ids)) == 5, "Each record must have a unique target_id"
        for tid in target_ids:
            assert isinstance(tid, str) and len(tid) > 0

    def test_parent_target_id_points_to_input(self):
        """parent_target_id equals the source item's target_id exactly."""
        guid = _uuid()
        parent_tid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent = _make_source_item(guid, parent_nid, target_id=parent_tid)

        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[parent], is_first_stage=False, action_name="transform")
        enriched = _enrich_lineage(result, ctx)

        assert enriched.data[0]["parent_target_id"] == parent_tid

    def test_root_target_id_propagated_from_ancestor(self):
        """root_target_id set at stage 1 carries unchanged through stages 2 and 3."""
        guid = _uuid()
        root_tid = _uuid()

        # Stage 1 item
        stage1_nid = f"extract_{_uuid()}"
        stage1 = _make_source_item(guid, stage1_nid, target_id=_uuid(), root_target_id=root_tid)

        # Stage 2
        r2 = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx2 = _make_context(source_data=[stage1], is_first_stage=False, action_name="transform")
        e2 = _enrich_lineage(r2, ctx2)
        item2 = e2.data[0]
        item2["target_id"] = _uuid()

        assert item2["root_target_id"] == root_tid

        # Stage 3
        r3 = ProcessingResult.success(
            data=[{"content": {"v": 2}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx3 = _make_context(source_data=[item2], is_first_stage=False, action_name="summarize")
        e3 = _enrich_lineage(r3, ctx3)
        item3 = e3.data[0]

        assert item3["root_target_id"] == root_tid, "root_target_id must propagate unchanged"

    def test_first_stage_no_ancestry_fields(self):
        """First-stage enrichment sets no parent_target_id or root_target_id."""
        guid = _uuid()
        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[], is_first_stage=True, action_name="ingest")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert "parent_target_id" not in item
        assert "root_target_id" not in item

    def test_root_target_id_initialized_from_parent_target_id(self):
        """When parent has target_id but no root_target_id, root = parent's target_id."""
        guid = _uuid()
        parent_tid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        # Parent has target_id but NO root_target_id (simulates stage 1 output)
        parent = _make_source_item(guid, parent_nid, target_id=parent_tid)

        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[parent], is_first_stage=False, action_name="transform")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert item["root_target_id"] == parent_tid
        assert item["parent_target_id"] == parent_tid


# ---------------------------------------------------------------------------
# TestLLMRecordMode
# ---------------------------------------------------------------------------


class TestLLMRecordMode:
    """LLM actions in RECORD granularity — per-record lineage via source_guid lookup."""

    def test_per_record_lineage_correct(self):
        """RECORD mode: each output links to its input via source_guid match."""
        guid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent_tid = _uuid()
        parent = _make_source_item(guid, parent_nid, target_id=parent_tid)

        result = ProcessingResult.success(
            data=[{"content": {"response": "hello"}, "source_guid": guid}],
            source_guid=guid,
        )
        # RECORD mode: current_item set for per-item parent lookup
        ctx = _make_context(
            source_data=[parent],
            is_first_stage=False,
            action_name="llm_action",
            current_item=parent,
        )
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert item["node_id"].startswith("llm_action_")
        assert item["lineage"] == [parent_nid, item["node_id"]]
        assert item["parent_target_id"] == parent_tid

    def test_metadata_fields_present_after_full_enrichment(self):
        """After full enrichment, LLM output has all required metadata fields."""
        guid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent = _make_source_item(guid, parent_nid, target_id=_uuid())

        result = ProcessingResult.success(
            data=[{"content": {"response": "hi"}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(
            source_data=[parent],
            is_first_stage=False,
            action_name="llm_action",
            current_item=parent,
        )
        enriched = _enrich_full(result, ctx)
        item = enriched.data[0]

        assert "node_id" in item
        assert "lineage" in item
        assert "target_id" in item
        assert "source_guid" in item
        assert "parent_target_id" in item

    def test_llm_record_mode_multiple_source_records(self):
        """When source_data has multiple records, per-item lookup finds correct parent."""
        guids = [_uuid() for _ in range(3)]
        parents = [
            _make_source_item(guids[i], f"extract_{_uuid()}", target_id=_uuid()) for i in range(3)
        ]

        # Process record at index 1 — should find parents[1] via source_guid match
        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guids[1]}],
            source_guid=guids[1],
        )
        ctx = _make_context(
            source_data=parents,
            is_first_stage=False,
            action_name="llm_action",
        )
        enriched = _enrich_lineage(result, ctx)

        assert enriched.data[0]["parent_target_id"] == parents[1]["target_id"]
        assert parents[1]["node_id"] in enriched.data[0]["lineage"]


# ---------------------------------------------------------------------------
# TestToolRecordMode
# ---------------------------------------------------------------------------


class TestToolRecordMode:
    """TOOL actions in RECORD granularity — same enrichment as LLM."""

    def test_tool_record_lineage_matches_llm(self):
        """TOOL RECORD mode produces identical lineage structure as LLM RECORD mode."""
        guid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent_tid = _uuid()
        root_tid = _uuid()
        parent = _make_source_item(guid, parent_nid, target_id=parent_tid, root_target_id=root_tid)

        # LLM result
        llm_result = ProcessingResult.success(
            data=[{"content": {"llm_out": True}, "source_guid": guid}],
            source_guid=guid,
        )
        llm_ctx = _make_context(
            source_data=[parent],
            is_first_stage=False,
            action_name="llm_action",
            current_item=parent,
        )
        llm_enriched = _enrich_lineage(llm_result, llm_ctx)

        # TOOL result (same source, same pattern — enrichment is identical)
        tool_result = ProcessingResult.success(
            data=[{"content": {"tool_out": True}, "source_guid": guid}],
            source_guid=guid,
        )
        tool_ctx = _make_context(
            source_data=[parent],
            is_first_stage=False,
            action_name="tool_action",
            current_item=parent,
        )
        tool_enriched = _enrich_lineage(tool_result, tool_ctx)

        # Both should have same lineage structure (different node_ids due to action names)
        llm_item = llm_enriched.data[0]
        tool_item = tool_enriched.data[0]

        assert llm_item["parent_target_id"] == tool_item["parent_target_id"] == parent_tid
        assert llm_item["root_target_id"] == tool_item["root_target_id"] == root_tid
        assert len(llm_item["lineage"]) == len(tool_item["lineage"]) == 2
        assert llm_item["lineage"][0] == tool_item["lineage"][0] == parent_nid

    def test_tool_record_mode_fields_present(self):
        """TOOL RECORD output has all required metadata fields after full enrichment."""
        guid = _uuid()
        parent = _make_source_item(guid, f"extract_{_uuid()}", target_id=_uuid())

        result = ProcessingResult.success(
            data=[{"content": {"tool_out": True}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(
            source_data=[parent],
            is_first_stage=False,
            action_name="tool_action",
            current_item=parent,
        )
        enriched = _enrich_full(result, ctx)
        item = enriched.data[0]

        assert "node_id" in item
        assert "lineage" in item
        assert "target_id" in item
        assert "source_guid" in item


# ---------------------------------------------------------------------------
# TestToolFileMode
# ---------------------------------------------------------------------------


class TestToolFileMode:
    """TOOL actions in FILE granularity — source_mapping based lineage."""

    def test_source_mapping_resolves_correct_parent(self):
        """source_mapping {0:0, 1:1, 2:2}: each output traces to its specific input."""
        sources = [
            _make_source_item(_uuid(), f"extract_{_uuid()}", target_id=_uuid()) for _ in range(3)
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"out": i}} for i in range(3)],
            source_guid=None,
            source_mapping={0: 0, 1: 1, 2: 2},
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="file_tool")
        enriched = _enrich_lineage(result, ctx)

        for i in range(3):
            item = enriched.data[i]
            assert item["parent_target_id"] == sources[i]["target_id"]
            assert sources[i]["node_id"] in item["lineage"]
            assert item["node_id"] in item["lineage"]

    def test_source_mapping_many_to_one_merge(self):
        """source_mapping {0: [0,1,2]}: merged output has lineage_sources."""
        sources = [
            _make_source_item(f"guid_{i}", f"extract_{_uuid()}", target_id=_uuid())
            for i in range(3)
        ]
        source_nids = [s["node_id"] for s in sources]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"merged": True}}],
            source_guid=None,
            source_mapping={0: [0, 1, 2]},
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="merge_tool")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        # lineage built from first source
        assert sources[0]["node_id"] in item["lineage"]
        assert item["node_id"] in item["lineage"]
        # lineage_sources has all parent node_ids
        assert "lineage_sources" in item
        assert len(item["lineage_sources"]) == 3
        for nid in source_nids:
            assert nid in item["lineage_sources"]
        # Ancestry from first source
        assert item["parent_target_id"] == sources[0]["target_id"]

    def test_no_source_mapping_falls_back_to_guid_scan(self):
        """Without source_mapping, enricher uses source_guid to find parent."""
        guid_a = _uuid()
        guid_b = _uuid()
        node_a = f"extract_{_uuid()}"
        node_b = f"extract_{_uuid()}"
        sources = [
            _make_source_item(guid_a, node_a, target_id=_uuid()),
            _make_source_item(guid_b, node_b, target_id=_uuid()),
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"content": {"v": 1}, "source_guid": guid_a},
                {"content": {"v": 2}, "source_guid": guid_b},
            ],
            source_guid=None,
            source_mapping=None,  # No mapping — fallback
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="file_tool")
        enriched = _enrich_lineage(result, ctx)

        assert node_a in enriched.data[0]["lineage"]
        assert node_b in enriched.data[1]["lineage"]
        assert enriched.data[0]["parent_target_id"] == sources[0]["target_id"]
        assert enriched.data[1]["parent_target_id"] == sources[1]["target_id"]

    def test_shared_source_guid_uses_index_not_scan(self):
        """When records share source_guid, source_mapping index resolves the right parent."""
        shared_guid = "shared-guid"
        sources = [
            _make_source_item(shared_guid, f"flatten_{_uuid()}", target_id=_uuid())
            for _ in range(5)
        ]

        # 3 outputs, each mapped to a specific input by index
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"dedup": i}, "source_guid": shared_guid} for i in range(3)],
            source_guid=None,
            source_mapping={0: 0, 1: 2, 2: 4},
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="dedup_tool")
        enriched = _enrich_lineage(result, ctx)

        # Output 0 → input 0
        assert enriched.data[0]["parent_target_id"] == sources[0]["target_id"]
        # Output 1 → input 2
        assert enriched.data[1]["parent_target_id"] == sources[2]["target_id"]
        # Output 2 → input 4
        assert enriched.data[2]["parent_target_id"] == sources[4]["target_id"]

    def test_source_mapping_out_of_bounds_produces_root_lineage(self):
        """Out-of-bounds source_mapping index: output still gets node_id and lineage."""
        sources = [_make_source_item(_uuid(), f"extract_{_uuid()}", target_id=_uuid())]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"v": 1}}],
            source_guid=None,
            source_mapping={0: 99},  # Out of bounds
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="file_tool")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        # Should still get node_id and lineage (as root, since parent lookup failed)
        assert "node_id" in item
        assert "lineage" in item
        assert item["lineage"] == [item["node_id"]]

    def test_file_mode_tool_multiple_outputs_get_indexed_node_ids(self):
        """N outputs: node_id gets _{i} suffix for disambiguation."""
        sources = [
            _make_source_item(_uuid(), f"extract_{_uuid()}", target_id=_uuid()) for _ in range(4)
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"out": i}} for i in range(4)],
            source_guid=None,
            source_mapping={i: i for i in range(4)},
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="file_tool")
        enriched = _enrich_lineage(result, ctx)

        node_ids = [item["node_id"] for item in enriched.data]
        assert len(set(node_ids)) == 4, "All node_ids must be unique"
        for i, item in enumerate(enriched.data):
            assert item["node_id"].endswith(f"_{i}")


# ---------------------------------------------------------------------------
# TestHITLFileMode
# ---------------------------------------------------------------------------


class TestHITLFileMode:
    """HITL FILE mode — identity source_mapping, lineage extension."""

    def test_hitl_preserves_full_lineage(self):
        """HITL output extends parent lineage: [ancestor, parent, hitl_node]."""
        ancestor_nid = f"ingest_{_uuid()}"
        guids = [_uuid() for _ in range(3)]
        sources = []
        for i in range(3):
            nid = f"extract_{_uuid()}"
            sources.append(
                _make_source_item(
                    guids[i],
                    nid,
                    lineage=[ancestor_nid, nid],
                    target_id=_uuid(),
                    root_target_id=_uuid(),
                )
            )

        # HITL identity mapping (same as HITLStrategy builds)
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"content": {"hitl_status": "approved"}, "source_guid": guids[i]} for i in range(3)
            ],
            source_guid=None,
            source_mapping={0: 0, 1: 1, 2: 2},
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="review")
        enriched = _enrich_lineage(result, ctx)

        for i in range(3):
            lineage = enriched.data[i]["lineage"]
            # Full chain: ancestor → parent → hitl
            assert ancestor_nid in lineage, "Ancestor node lost"
            assert sources[i]["node_id"] in lineage, "Parent node lost"
            assert enriched.data[i]["node_id"] in lineage, "HITL node not appended"
            assert len(lineage) == 3

    def test_hitl_identity_mapping(self):
        """HITL source_mapping is {i:i} — each output[i] traces to source[i]."""
        sources = [
            _make_source_item(_uuid(), f"extract_{_uuid()}", target_id=_uuid()) for _ in range(4)
        ]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"content": {"hitl_status": "approved"}, "source_guid": sources[i]["source_guid"]}
                for i in range(4)
            ],
            source_guid=None,
            source_mapping={i: i for i in range(4)},
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="review")
        enriched = _enrich_lineage(result, ctx)

        for i in range(4):
            assert enriched.data[i]["parent_target_id"] == sources[i]["target_id"]
            assert sources[i]["node_id"] in enriched.data[i]["lineage"]

    def test_hitl_ancestry_chain_not_truncated(self):
        """HITL preserves root_target_id from deep ancestry chain."""
        root_tid = _uuid()
        parent_tid = _uuid()
        ancestor_nid = f"ingest_{_uuid()}"
        parent_nid = f"extract_{_uuid()}"

        source = _make_source_item(
            _uuid(),
            parent_nid,
            lineage=[ancestor_nid, parent_nid],
            target_id=parent_tid,
            root_target_id=root_tid,
        )

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"hitl_status": "approved"}, "source_guid": source["source_guid"]}],
            source_guid=None,
            source_mapping={0: 0},
        )
        ctx = _make_context(source_data=[source], is_first_stage=False, action_name="review")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert item["root_target_id"] == root_tid, "root_target_id must survive HITL"
        assert item["parent_target_id"] == parent_tid
        assert ancestor_nid in item["lineage"]
        assert parent_nid in item["lineage"]

    def test_hitl_without_source_mapping_truncates_lineage(self):
        """Regression guard: without source_mapping + mismatched guid, lineage truncates."""
        source = _make_source_item(
            _uuid(),  # Different from output guid
            f"extract_{_uuid()}",
            target_id=_uuid(),
        )
        output_guid = _uuid()  # Different guid — won't match source

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"hitl_status": "approved"}, "source_guid": output_guid}],
            source_guid=None,
            # No source_mapping — bug condition
        )
        ctx = _make_context(source_data=[source], is_first_stage=False, action_name="review")
        enriched = _enrich_lineage(result, ctx)
        lineage = enriched.data[0]["lineage"]

        # Without source_mapping and mismatched guid, parent lookup fails → truncated
        assert len(lineage) == 1, "Lineage should be truncated to just [node_id]"
        assert source["node_id"] not in lineage


# ---------------------------------------------------------------------------
# TestDiamondPattern
# ---------------------------------------------------------------------------


class TestDiamondPattern:
    """Diamond: A→B, A→C, [B,C]→D (fan-out then fan-in)."""

    def test_diamond_merge_preserves_all_parent_node_ids(self):
        """Fan-in merge: output.lineage_sources contains both B and C node_ids."""
        guid_a = _uuid()
        root_tid = _uuid()

        # A: first stage
        a_nid = f"extract_{_uuid()}"

        # B: from A
        b_nid = f"branch_b_{_uuid()}"
        b_tid = _uuid()
        b = _make_source_item(
            guid_a,
            b_nid,
            lineage=[a_nid, b_nid],
            target_id=b_tid,
            root_target_id=root_tid,
        )

        # C: from A
        c_nid = f"branch_c_{_uuid()}"
        c_tid = _uuid()
        c = _make_source_item(
            guid_a,
            c_nid,
            lineage=[a_nid, c_nid],
            target_id=c_tid,
            root_target_id=root_tid,
        )

        # D: merge B + C
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"merged": True}}],
            source_guid=None,
            source_mapping={0: [0, 1]},
        )
        ctx = _make_context(source_data=[b, c], is_first_stage=False, action_name="merge")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert "lineage_sources" in item
        assert b_nid in item["lineage_sources"]
        assert c_nid in item["lineage_sources"]
        # Ancestry from first source (B)
        assert item["parent_target_id"] == b_tid
        assert item["root_target_id"] == root_tid


# ---------------------------------------------------------------------------
# TestMapReducePattern
# ---------------------------------------------------------------------------


class TestMapReducePattern:
    """Map-Reduce: one input splits, each processed independently, then merged."""

    def test_map_reduce_root_target_id_traces_to_origin(self):
        """After split → process → merge, root_target_id still points to original."""
        root_tid = _uuid()
        original_nid = f"ingest_{_uuid()}"

        # Simulate 3 map outputs from same origin
        map_outputs = []
        for i in range(3):
            nid = f"map_{_uuid()}"
            item = _make_source_item(
                f"guid_{i}",
                nid,
                lineage=[original_nid, nid],
                target_id=_uuid(),
                root_target_id=root_tid,
            )
            map_outputs.append(item)

        # Reduce: merge all 3
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"reduced": True}}],
            source_guid=None,
            source_mapping={0: [0, 1, 2]},
        )
        ctx = _make_context(source_data=map_outputs, is_first_stage=False, action_name="reduce")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert item["root_target_id"] == root_tid, "Reduce must trace to original root"
        assert original_nid in item["lineage"], "Original ancestor must be in lineage"


# ---------------------------------------------------------------------------
# TestUniformShape
# ---------------------------------------------------------------------------


class TestUniformShape:
    """Verify all action types produce the same set of metadata fields."""

    REQUIRED_FIELDS = {"node_id", "lineage", "target_id", "source_guid"}

    def _enriched_item(self, action_name, source_mapping=None, is_first_stage=False):
        """Helper: create and enrich a single output item."""
        guid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent = _make_source_item(guid, parent_nid, target_id=_uuid())

        if source_mapping is not None:
            result = ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                data=[{"content": {"out": 1}, "source_guid": guid}],
                source_guid=None,
                source_mapping=source_mapping,
            )
        else:
            result = ProcessingResult.success(
                data=[{"content": {"out": 1}, "source_guid": guid}],
                source_guid=guid,
            )

        ctx = _make_context(
            source_data=[parent] if not is_first_stage else [],
            is_first_stage=is_first_stage,
            action_name=action_name,
            current_item=parent if not is_first_stage and source_mapping is None else None,
        )
        enriched = _enrich_full(result, ctx)
        return enriched.data[0]

    def test_all_action_types_produce_node_id(self):
        """node_id present and valid for LLM, TOOL-RECORD, TOOL-FILE, HITL-FILE."""
        for name, sm in [
            ("llm_action", None),
            ("tool_record", None),
            ("tool_file", {0: 0}),
            ("hitl_review", {0: 0}),
        ]:
            item = self._enriched_item(name, source_mapping=sm)
            assert "node_id" in item, f"{name}: missing node_id"
            assert isinstance(item["node_id"], str), f"{name}: node_id not str"
            assert item["node_id"].startswith(f"{name}_"), f"{name}: wrong prefix"

    def test_all_action_types_produce_target_id(self):
        """target_id present and non-empty for all action types."""
        for name, sm in [
            ("llm_action", None),
            ("tool_record", None),
            ("tool_file", {0: 0}),
            ("hitl_review", {0: 0}),
        ]:
            item = self._enriched_item(name, source_mapping=sm)
            assert "target_id" in item, f"{name}: missing target_id"
            assert isinstance(item["target_id"], str) and item["target_id"], (
                f"{name}: target_id empty or not str"
            )

    def test_all_action_types_produce_lineage_array(self):
        """lineage is a non-empty list of strings for all action types."""
        for name, sm in [
            ("llm_action", None),
            ("tool_record", None),
            ("tool_file", {0: 0}),
            ("hitl_review", {0: 0}),
        ]:
            item = self._enriched_item(name, source_mapping=sm)
            assert "lineage" in item, f"{name}: missing lineage"
            assert isinstance(item["lineage"], list), f"{name}: lineage not list"
            assert len(item["lineage"]) > 0, f"{name}: lineage empty"
            for nid in item["lineage"]:
                assert isinstance(nid, str), f"{name}: lineage entry not str"

    def test_all_action_types_produce_source_guid(self):
        """source_guid present for all action types."""
        for name, sm in [
            ("llm_action", None),
            ("tool_record", None),
            ("tool_file", {0: 0}),
            ("hitl_review", {0: 0}),
        ]:
            item = self._enriched_item(name, source_mapping=sm)
            assert "source_guid" in item, f"{name}: missing source_guid"
            assert isinstance(item["source_guid"], str), f"{name}: source_guid not str"

    def test_first_stage_uniform_shape(self):
        """First-stage items also have all required fields after full enrichment."""
        item = self._enriched_item("ingest", is_first_stage=True)
        for field in self.REQUIRED_FIELDS:
            assert field in item, f"First-stage missing {field}"

    def test_subsequent_stage_has_ancestry_fields(self):
        """Subsequent-stage items additionally have parent_target_id."""
        for name, sm in [
            ("llm_action", None),
            ("tool_file", {0: 0}),
            ("hitl_review", {0: 0}),
        ]:
            item = self._enriched_item(name, source_mapping=sm)
            assert "parent_target_id" in item, f"{name}: missing parent_target_id"
            assert "root_target_id" in item, f"{name}: missing root_target_id"


# ---------------------------------------------------------------------------
# TestEdgeCases — failure modes and broken inputs
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and failure modes that aren't happy paths."""

    def test_empty_result_data_does_not_crash(self):
        """Enriching a result with 0 records should not crash."""
        result = ProcessingResult.success(data=[], source_guid=_uuid())
        ctx = _make_context(source_data=[], is_first_stage=True, action_name="test")
        enriched = _enrich_lineage(result, ctx)

        assert enriched.data == []
        assert enriched.node_id is not None  # base node_id still assigned

    def test_non_first_stage_with_empty_source_data(self):
        """Non-first-stage with no source_data: parent lookup returns None, lineage = [self]."""
        guid = _uuid()
        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        # Misconfigured: is_first_stage=False but no source_data
        ctx = _make_context(source_data=[], is_first_stage=False, action_name="orphan")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        # No parent found → lineage is just [self], no ancestry fields
        assert item["lineage"] == [item["node_id"]]
        assert "parent_target_id" not in item

    def test_skipped_result_still_gets_lineage(self):
        """SKIPPED results pass through enrichment — they must get node_id and lineage."""
        guid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent = _make_source_item(guid, parent_nid, target_id=_uuid())

        result = ProcessingResult.skipped(
            passthrough_data={"content": {"original": True}, "source_guid": guid},
            reason="guard skip",
            source_guid=guid,
        )
        ctx = _make_context(
            source_data=[parent],
            is_first_stage=False,
            action_name="guarded_action",
            current_item=parent,
        )
        enriched = _enrich_lineage(result, ctx)

        assert enriched.status == ProcessingStatus.SKIPPED
        assert len(enriched.data) == 1
        item = enriched.data[0]
        assert "node_id" in item
        assert "lineage" in item
        assert parent_nid in item["lineage"]

    def test_parent_item_without_lineage_key(self):
        """Parent that has target_id but no lineage field: output lineage = [self]."""
        guid = _uuid()
        parent_tid = _uuid()
        # Manually construct parent WITHOUT lineage key
        parent = {"source_guid": guid, "node_id": f"extract_{_uuid()}", "target_id": parent_tid}

        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[parent], is_first_stage=False, action_name="transform")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        # Parent has no lineage → build_lineage returns [node_id]
        assert item["lineage"] == [item["node_id"]]
        # But ancestry chain IS propagated (parent has target_id)
        assert item["parent_target_id"] == parent_tid

    def test_pre_existing_lineage_fields_overwritten(self):
        """If output already has node_id/lineage, enrichment overwrites them."""
        guid = _uuid()
        parent_nid = f"extract_{_uuid()}"
        parent = _make_source_item(guid, parent_nid, target_id=_uuid())

        # Output has pre-existing (wrong) lineage fields
        result = ProcessingResult.success(
            data=[
                {
                    "content": {"v": 1},
                    "source_guid": guid,
                    "node_id": "stale_node_abc",
                    "lineage": ["garbage_xyz"],
                }
            ],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[parent], is_first_stage=False, action_name="transform")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        # Enrichment must overwrite stale values
        assert item["node_id"] != "stale_node_abc"
        assert item["node_id"].startswith("transform_")
        assert "garbage_xyz" not in item["lineage"]
        assert parent_nid in item["lineage"]

    def test_many_to_one_with_partial_oob_indices(self):
        """Many-to-one source_mapping where some indices are valid, some OOB."""
        sources = [
            _make_source_item(f"guid_{i}", f"extract_{_uuid()}", target_id=_uuid())
            for i in range(2)
        ]

        # source_mapping says merge indices [0, 1, 99] — 99 is OOB
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"merged": True}}],
            source_guid=None,
            source_mapping={0: [0, 1, 99]},
        )
        ctx = _make_context(source_data=sources, is_first_stage=False, action_name="merge_tool")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        # Should still produce lineage from the valid sources
        assert "lineage" in item
        assert "node_id" in item
        # lineage_sources should have 2 valid entries (index 99 skipped)
        assert "lineage_sources" in item
        assert len(item["lineage_sources"]) == 2

    def test_source_mapping_with_empty_source_list(self):
        """Many-to-one with empty source list: lineage = [self]."""
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"content": {"merged": True}}],
            source_guid=None,
            source_mapping={0: []},
        )
        ctx = _make_context(source_data=[], is_first_stage=False, action_name="merge_tool")
        enriched = _enrich_lineage(result, ctx)
        item = enriched.data[0]

        assert item["lineage"] == [item["node_id"]]
        assert "lineage_sources" not in item


# ---------------------------------------------------------------------------
# TestFilteredResultBypass
# ---------------------------------------------------------------------------


class TestFilteredResultBypass:
    """FILTERED results bypass enrichment entirely."""

    def test_filtered_result_has_no_lineage_fields(self):
        result = ProcessingResult.filtered(source_guid=_uuid())
        ctx = _make_context(source_data=[], is_first_stage=True, action_name="test")
        enriched = _enrich_lineage(result, ctx)

        assert enriched.data == []
        assert enriched.status == ProcessingStatus.FILTERED

    def test_filtered_result_bypasses_required_fields_enricher(self):
        result = ProcessingResult.filtered(source_guid=_uuid())
        ctx = _make_context(source_data=[], is_first_stage=True, action_name="test")
        enriched = _enrich_full(result, ctx)

        assert enriched.data == []
        assert enriched.status == ProcessingStatus.FILTERED


# ---------------------------------------------------------------------------
# TestResultNodeId
# ---------------------------------------------------------------------------


class TestResultNodeId:
    """Verify that ProcessingResult.node_id is set by LineageEnricher."""

    def test_result_node_id_set_after_enrichment(self):
        guid = _uuid()
        result = ProcessingResult.success(
            data=[{"content": {"v": 1}, "source_guid": guid}],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[], is_first_stage=True, action_name="test_action")

        assert result.node_id is None
        enriched = _enrich_lineage(result, ctx)
        assert enriched.node_id is not None
        assert enriched.node_id.startswith("test_action_")

    def test_result_node_id_is_base_without_index(self):
        """Result.node_id is the base, items get _i suffixed."""
        guid = _uuid()
        result = ProcessingResult.success(
            data=[{"content": {"v": i}, "source_guid": guid} for i in range(3)],
            source_guid=guid,
        )
        ctx = _make_context(source_data=[], is_first_stage=True, action_name="split")
        enriched = _enrich_lineage(result, ctx)

        base = enriched.node_id
        assert base is not None
        for i, item in enumerate(enriched.data):
            assert item["node_id"] == f"{base}_{i}"
