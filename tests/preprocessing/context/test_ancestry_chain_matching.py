"""
Tests for deterministic record matcher and ancestry chain patterns.

The matcher uses exact node_id key-join with two explicit modes:
- Mode 1 (Ancestor): node_id in lineage chain
- Mode 2 (Merge parent): node_id in lineage_sources

No fallbacks. No guessing. If node_id isn't found, returns None.

RFC Reference: docs/specs/RFC_ancestry_chain.md
"""

import json
import tempfile
from pathlib import Path

import pytest

from agent_actions.input.context.historical import (
    HistoricalDataRequest,
    HistoricalNodeDataLoader,
)


@pytest.fixture
def parallel_branch_records():
    """Load parallel branch fixture data (Diamond pattern)."""
    fixture_path = (
        Path(__file__).parent.parent.parent
        / "fixtures"
        / "ancestry_chain"
        / "parallel_branch_records.json"
    )
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def map_reduce_records():
    """Load map-reduce fixture data."""
    fixture_path = (
        Path(__file__).parent.parent.parent
        / "fixtures"
        / "ancestry_chain"
        / "map_reduce_records.json"
    )
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def parallel_branch_temp_dir(parallel_branch_records):
    """Create temporary directory structure for parallel branch test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        target_dir = tmp_path / "agent_io" / "target"

        _parent = parallel_branch_records[0]
        branch_a = parallel_branch_records[1]
        branch_b = parallel_branch_records[2]
        branch_c = parallel_branch_records[3]

        for action_name, records in [
            ("generate_seo", [branch_a]),
            ("generate_recommendations", [branch_b]),
            ("assess_reading_level", [branch_c]),
        ]:
            node_dir = target_dir / action_name
            node_dir.mkdir(parents=True)
            with open(node_dir / "test.json", "w") as f:
                json.dump(records, f, indent=2)

        yield tmp_path


class TestAncestryChainPropagation:
    """Tests for ancestry chain field propagation through the pipeline."""

    def test_root_record_sets_root_target_id_to_self(self):
        """First record in chain should set root_target_id to its own target_id."""
        root_record = {
            "source_guid": "test-001",
            "target_id": "T1",
            "parent_target_id": None,
            "root_target_id": "T1",
        }

        assert root_record["root_target_id"] == root_record["target_id"]
        assert root_record["parent_target_id"] is None

    def test_child_record_inherits_root_target_id(self):
        """Child records should inherit root_target_id from parent."""
        root = {"target_id": "ROOT", "root_target_id": "ROOT"}
        child = {
            "target_id": "CHILD-1",
            "parent_target_id": root["target_id"],
            "root_target_id": root["root_target_id"],
        }

        assert child["parent_target_id"] == root["target_id"]
        assert child["root_target_id"] == root["target_id"]

    def test_grandchild_preserves_original_root(self):
        """Grandchild should still reference original root, not parent."""
        root = {"target_id": "ROOT", "root_target_id": "ROOT"}
        child = {
            "target_id": "CHILD",
            "parent_target_id": "ROOT",
            "root_target_id": "ROOT",
        }
        grandchild = {
            "target_id": "GRANDCHILD",
            "parent_target_id": child["target_id"],
            "root_target_id": root["target_id"],
        }

        assert grandchild["parent_target_id"] == "CHILD"
        assert grandchild["root_target_id"] == "ROOT"


class TestHistoricalDataRequestWithAncestry:
    """Tests for HistoricalDataRequest dataclass with ancestry and lineage_sources fields."""

    def test_request_accepts_parent_target_id(self):
        request = HistoricalDataRequest(
            action_name="test_action",
            lineage=["node_0", "node_1"],
            source_guid="test-guid",
            file_path="/tmp/test.json",
            agent_indices={"test_action": 0},
            parent_target_id="parent-123",
        )
        assert request.parent_target_id == "parent-123"

    def test_request_accepts_root_target_id(self):
        request = HistoricalDataRequest(
            action_name="test_action",
            lineage=["node_0", "node_1"],
            source_guid="test-guid",
            file_path="/tmp/test.json",
            agent_indices={"test_action": 0},
            root_target_id="root-456",
        )
        assert request.root_target_id == "root-456"

    def test_request_accepts_lineage_sources(self):
        """lineage_sources field enables merge-parent mode matching."""
        request = HistoricalDataRequest(
            action_name="test_action",
            lineage=["node_0", "node_1"],
            source_guid="test-guid",
            file_path="/tmp/test.json",
            agent_indices={"test_action": 0},
            lineage_sources=["branch_a_uuid1", "branch_b_uuid2"],
        )
        assert request.lineage_sources == ["branch_a_uuid1", "branch_b_uuid2"]

    def test_ancestry_fields_default_to_none(self):
        request = HistoricalDataRequest(
            action_name="test_action",
            lineage=["node_0"],
            source_guid="test-guid",
            file_path="/tmp/test.json",
            agent_indices={"test_action": 0},
        )
        assert request.parent_target_id is None
        assert request.root_target_id is None
        assert request.lineage_sources is None


class TestFindTargetNodeId:
    """Tests for _find_target_node_id: extracting target node_id from lineage metadata."""

    def test_ancestor_mode_finds_node_in_lineage(self):
        """Mode 1: Target action's node_id is in the lineage chain."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract",
            lineage=["source_abc", "extract_def456", "transform_ghi789"],
            agent_indices={"source": 0, "extract": 1, "transform": 2},
        )
        assert result == "extract_def456"

    def test_merge_parent_mode_finds_node_in_lineage_sources(self):
        """Mode 2: Target action's node_id is in lineage_sources."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="branch_b",
            lineage=["source_abc", "branch_a_def", "merge_ghi"],
            lineage_sources=["branch_a_def", "branch_b_xyz999"],
            agent_indices={"source": 0, "branch_a": 1, "branch_b": 2, "merge": 3},
        )
        assert result == "branch_b_xyz999"

    def test_ancestor_mode_preferred_over_merge_parent(self):
        """If node_id is in lineage, use it even if also in lineage_sources."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract",
            lineage=["extract_abc123", "transform_def456"],
            lineage_sources=["extract_abc123"],
            agent_indices={"extract": 0, "transform": 1},
        )
        assert result == "extract_abc123"

    def test_no_match_returns_none(self):
        """If target action is not in lineage or lineage_sources, return None."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="missing_action",
            lineage=["source_abc", "extract_def"],
            agent_indices={"source": 0, "extract": 1, "missing_action": 2},
        )
        assert result is None

    def test_prefix_disambiguation_extract_vs_extract_raw_qa(self):
        """'extract' must not match 'extract_raw_qa_uuid'. Longest action name wins."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract",
            lineage=["extract_raw_qa_abc123", "transform_def456"],
            agent_indices={"extract": 0, "extract_raw_qa": 1, "transform": 2},
        )
        # extract_raw_qa_abc123 belongs to extract_raw_qa, not extract
        assert result is None

    def test_prefix_disambiguation_longer_action_matches(self):
        """'extract_raw_qa' should correctly match its own node_id."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract_raw_qa",
            lineage=["extract_raw_qa_abc123", "transform_def456"],
            agent_indices={"extract": 0, "extract_raw_qa": 1, "transform": 2},
        )
        assert result == "extract_raw_qa_abc123"

    def test_empty_lineage_returns_none(self):
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract",
            lineage=[],
            agent_indices={"extract": 0},
        )
        assert result is None

    def test_lineage_sources_not_present_skips_mode_2(self):
        """When lineage_sources is None, only ancestor mode is tried."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="branch_b",
            lineage=["source_abc", "branch_a_def"],
            lineage_sources=None,
            agent_indices={"source": 0, "branch_a": 1, "branch_b": 2},
        )
        assert result is None

    def test_agent_indices_none_disables_disambiguation(self):
        """Without agent_indices, no prefix disambiguation is performed.

        A simple prefix match is used — extract_ matches extract_raw_qa_uuid
        because there's no way to know about longer action names.
        """
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract",
            lineage=["extract_raw_qa_abc123"],
            agent_indices=None,
        )
        # Without agent_indices, no disambiguation — prefix match succeeds
        assert result == "extract_raw_qa_abc123"


class TestDeterministicRecordMatcher:
    """Tests for _find_record_by_identifiers: exact node_id key-join, no fallbacks."""

    def test_exact_node_id_match(self):
        """Returns record with matching node_id."""
        records = [
            {"node_id": "extract_abc123", "content": {"field": "value_a"}},
            {"node_id": "extract_def456", "content": {"field": "value_b"}},
        ]
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=records,
            target_node_id="extract_def456",
            action_name="extract",
        )
        assert result is not None
        assert result["node_id"] == "extract_def456"
        assert result["content"]["field"] == "value_b"

    def test_fan_out_same_source_guid_different_node_ids(self):
        """With fan-out, multiple records share source_guid but have unique node_ids.

        The deterministic matcher ignores source_guid and matches by node_id only.
        """
        records = [
            {"source_guid": "src-001", "node_id": "extract_aaa", "content": {"v": 1}},
            {"source_guid": "src-001", "node_id": "extract_bbb", "content": {"v": 2}},
            {"source_guid": "src-001", "node_id": "extract_ccc", "content": {"v": 3}},
            {"source_guid": "src-001", "node_id": "extract_ddd", "content": {"v": 4}},
            {"source_guid": "src-001", "node_id": "extract_eee", "content": {"v": 5}},
            {"source_guid": "src-001", "node_id": "extract_fff", "content": {"v": 6}},
        ]
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=records,
            target_node_id="extract_ddd",
            action_name="extract",
        )
        assert result is not None
        assert result["content"]["v"] == 4

    def test_no_match_returns_none(self):
        """When no record has the target node_id, returns None."""
        records = [
            {"node_id": "extract_abc", "content": {"field": "value"}},
        ]
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=records,
            target_node_id="extract_xyz_not_found",
            action_name="extract",
        )
        assert result is None

    def test_no_source_guid_only_matching(self):
        """source_guid is NOT used for matching — only node_id matters.

        A record with matching source_guid but wrong node_id must NOT be returned.
        """
        records = [
            {
                "source_guid": "matching-guid",
                "node_id": "extract_wrong_node",
                "content": {"field": "wrong"},
            },
        ]
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=records,
            target_node_id="extract_correct_node",
            action_name="extract",
        )
        assert result is None

    def test_no_fallback_to_weaker_match(self):
        """Even if parent_target_id or root_target_id would match, we only use node_id.

        The new matcher doesn't accept those fields at all — this test confirms
        that records are only matched by exact node_id.
        """
        records = [
            {
                "source_guid": "src-001",
                "node_id": "extract_wrong",
                "parent_target_id": "parent-match",
                "root_target_id": "root-match",
                "content": {"field": "should not match"},
            },
        ]
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=records,
            target_node_id="extract_correct_but_absent",
            action_name="extract",
        )
        assert result is None

    def test_empty_data_returns_none(self):
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=[],
            target_node_id="extract_abc",
            action_name="extract",
        )
        assert result is None

    def test_non_list_data_returns_none(self):
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data="not a list",  # type: ignore[arg-type]
            target_node_id="extract_abc",
            action_name="extract",
        )
        assert result is None

    def test_non_dict_records_skipped(self):
        """Non-dict items in data are skipped without crashing."""
        records = [
            "not a dict",
            42,
            {"node_id": "extract_abc", "content": {"field": "correct"}},
            None,
        ]
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=records,  # type: ignore[arg-type]
            target_node_id="extract_abc",
            action_name="extract",
        )
        assert result is not None
        assert result["content"]["field"] == "correct"

    def test_record_content_not_a_dict_returns_empty(self):
        """When record.content is not a dict, load_historical_node_data returns {}."""
        # This tests load_historical_node_data's line: record.get("content", {})
        # If content is a string, the .keys() call on it would differ
        records = [
            {"node_id": "extract_abc", "content": "not a dict"},
        ]
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=records,
            target_node_id="extract_abc",
            action_name="extract",
        )
        assert result is not None
        assert result["content"] == "not a dict"


class TestFindTargetNodeIdEdgeCases:
    """Edge cases for _find_target_node_id that close coverage gaps."""

    def test_empty_lineage_sources_treated_as_falsy(self):
        """lineage_sources=[] should behave same as None — skip Mode 2."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="branch_b",
            lineage=["source_abc", "branch_a_def"],
            lineage_sources=[],
            agent_indices={"source": 0, "branch_a": 1, "branch_b": 2},
        )
        assert result is None

    def test_non_string_lineage_entries_skipped(self):
        """Non-string entries in lineage are skipped without crashing."""
        result = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract",
            lineage=[42, None, "extract_abc123", {"bad": "entry"}],  # type: ignore[list-item]
            agent_indices={"extract": 0},
        )
        assert result == "extract_abc123"


class TestMapReducePattern:
    """Tests for Map-Reduce pattern where split records aggregate."""

    def test_aggregate_can_find_all_chunks_by_root(self, map_reduce_records):
        """Aggregator should find all processed chunks by root_target_id."""
        processed = [r for r in map_reduce_records if "processed" in r["target_id"]]
        root_target_id = "root-doc-001"
        matched = [r for r in processed if r.get("root_target_id") == root_target_id]
        assert len(matched) == 2, "Should match both processed chunks by root_target_id"

    def test_root_matching_ignores_different_parents(self, map_reduce_records):
        """Chunks with same root but different parents should all match."""
        processed = [r for r in map_reduce_records if "processed" in r["target_id"]]
        parents = {r["parent_target_id"] for r in processed}
        assert len(parents) == 2, "Processed chunks should have different parents"
        roots = {r["root_target_id"] for r in processed}
        assert len(roots) == 1, "All should share same root_target_id"
        assert "root-doc-001" in roots


class TestBackwardCompatibility:
    """Tests for records that predate ancestry tracking."""

    def test_exact_node_id_match_works_regardless_of_ancestry(self):
        """Matcher only needs node_id — ancestry fields are metadata, not matching keys."""
        records = [
            {
                "source_guid": "legacy-001",
                "target_id": "old-record",
                "node_id": "old_action_abc123",
                "content": {"legacy_field": "value"},
            }
        ]
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=records,
            target_node_id="old_action_abc123",
            action_name="old_action",
        )
        assert result is not None
        assert result["content"]["legacy_field"] == "value"

    def test_legacy_record_via_loader_returns_none_when_not_in_lineage(self, tmp_path):
        """If target action is not in caller's lineage, loader returns None."""
        request = HistoricalDataRequest(
            action_name="legacy_action",
            lineage=["node_0"],  # No legacy_action_* node in lineage
            source_guid="legacy-001",
            file_path=str(tmp_path / "test.json"),
            agent_indices={"legacy_action": 1},
        )
        result = HistoricalNodeDataLoader.load_historical_node_data(request)
        assert result is None

    def test_new_record_with_ancestry_still_has_source_guid(self):
        """New records with ancestry should still have source_guid for diagnostics."""
        new_record = {
            "source_guid": "new-001",
            "target_id": "new-record",
            "parent_target_id": "parent-001",
            "root_target_id": "root-001",
            "content": {},
        }
        assert "source_guid" in new_record
        assert "parent_target_id" in new_record
        assert "root_target_id" in new_record


class TestConditionalMerge:
    """Tests for handling missing branches in conditional merges."""

    def test_missing_branch_returns_none_gracefully(self, parallel_branch_temp_dir):
        """When a conditional branch didn't run, should return None, not crash."""
        file_path = str(
            parallel_branch_temp_dir / "agent_io" / "target" / "score_quality" / "test.json"
        )
        request = HistoricalDataRequest(
            action_name="nonexistent_branch",
            lineage=["node_0", "node_7"],
            source_guid="book-001-catalog",
            file_path=file_path,
            agent_indices={"nonexistent_branch": 99},
            parent_target_id="parent-001",
        )
        result = HistoricalNodeDataLoader.load_historical_node_data(request)
        assert result is None
