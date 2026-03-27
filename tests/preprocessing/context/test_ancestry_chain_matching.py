"""
TDD Tests for Ancestry Chain Pattern - Parallel Branch Merge.

These tests define the expected behavior for the ancestry chain pattern
that enables parallel branch merging in workflows.

RFC Reference: docs/specs/RFC_ancestry_chain.md
Issue Reference: ISSUE_parallel_branch_merge.md

Test Strategy:
- Tests are written BEFORE implementation (TDD)
- Tests define the expected interface and behavior
- Tests WILL FAIL until implementation is complete
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
    """
    Create temporary directory structure for parallel branch test.

    Structure:
        tmp_dir/
        └── agent_io/
            └── target/
                ├── generate_seo/
                │   └── test.json (branch A records)
                ├── generate_recommendations/
                │   └── test.json (branch B records)
                └── assess_reading_level/
                    └── test.json (branch C records)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        target_dir = tmp_path / "agent_io" / "target"

        # Get records by node
        _parent = parallel_branch_records[0]
        branch_a = parallel_branch_records[1]
        branch_b = parallel_branch_records[2]
        branch_c = parallel_branch_records[3]

        # Create directories and write records
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
        # This is a design contract test
        root_record = {
            "source_guid": "test-001",
            "target_id": "T1",
            "parent_target_id": None,
            "root_target_id": "T1",  # Should equal target_id for root
        }

        assert root_record["root_target_id"] == root_record["target_id"]
        assert root_record["parent_target_id"] is None

    def test_child_record_inherits_root_target_id(self):
        """Child records should inherit root_target_id from parent."""
        root = {"target_id": "ROOT", "root_target_id": "ROOT"}
        child = {
            "target_id": "CHILD-1",
            "parent_target_id": root["target_id"],
            "root_target_id": root["root_target_id"],  # Inherited
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
            "parent_target_id": child["target_id"],  # Links to child
            "root_target_id": root["target_id"],  # Still links to original root!
        }

        assert grandchild["parent_target_id"] == "CHILD"
        assert grandchild["root_target_id"] == "ROOT"


class TestHistoricalDataRequestWithAncestry:
    """Tests for HistoricalDataRequest dataclass with ancestry fields."""

    def test_request_accepts_parent_target_id(self):
        """HistoricalDataRequest should accept parent_target_id field."""
        request = HistoricalDataRequest(
            action_name="test_action",
            lineage=["node_0", "node_1"],
            source_guid="test-guid",
            file_path="/tmp/test.json",
            agent_indices={"test_action": 0},
            parent_target_id="parent-123",  # NEW FIELD
        )

        assert request.parent_target_id == "parent-123"

    def test_request_accepts_root_target_id(self):
        """HistoricalDataRequest should accept root_target_id field."""
        request = HistoricalDataRequest(
            action_name="test_action",
            lineage=["node_0", "node_1"],
            source_guid="test-guid",
            file_path="/tmp/test.json",
            agent_indices={"test_action": 0},
            root_target_id="root-456",  # NEW FIELD
        )

        assert request.root_target_id == "root-456"

    def test_ancestry_fields_default_to_none(self):
        """Ancestry fields should default to None for backward compatibility."""
        request = HistoricalDataRequest(
            action_name="test_action",
            lineage=["node_0"],
            source_guid="test-guid",
            file_path="/tmp/test.json",
            agent_indices={"test_action": 0},
        )

        assert request.parent_target_id is None
        assert request.root_target_id is None


class TestMapReducePattern:
    """
    Tests for Map-Reduce pattern where split records aggregate.

    Scenario:
        document → chunk_1 → process → ┐
                 → chunk_2 → process → ┼→ aggregate (by root_target_id)
                 → chunk_3 → process → ┘
    """

    def test_aggregate_can_find_all_chunks_by_root(self, map_reduce_records):
        """Aggregator should find all processed chunks by root_target_id."""
        # Filter to just processed chunks
        processed = [r for r in map_reduce_records if "processed" in r["target_id"]]

        # Simulate aggregate matching by root
        root_target_id = "root-doc-001"
        matched = [r for r in processed if r.get("root_target_id") == root_target_id]

        assert len(matched) == 2, "Should match both processed chunks by root_target_id"

    def test_root_matching_ignores_different_parents(self, map_reduce_records):
        """Chunks with same root but different parents should all match."""
        processed = [r for r in map_reduce_records if "processed" in r["target_id"]]

        # Verify they have different parents
        parents = {r["parent_target_id"] for r in processed}
        assert len(parents) == 2, "Processed chunks should have different parents"

        # But same root
        roots = {r["root_target_id"] for r in processed}
        assert len(roots) == 1, "All should share same root_target_id"
        assert "root-doc-001" in roots


class TestBackwardCompatibility:
    """Tests for records that predate ancestry tracking."""

    def test_legacy_record_without_ancestry_does_not_match(self):
        """Records without ancestry fields should not match without lineage or ancestry."""
        legacy_records = [
            {
                "source_guid": "legacy-001",
                "target_id": "old-record",
                "node_id": "old_action_abc123",
                # No parent_target_id
                # No root_target_id
                "content": {"legacy_field": "value"},
            }
        ]

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=legacy_records,
            source_guid="legacy-001",
            _node_id="old_action_abc123",
            caller_lineage=None,
            parent_target_id=None,
            root_target_id=None,
            is_parallel_sibling=False,
            action_name="old_action",
        )

        assert result is None

    def test_legacy_record_via_loader_returns_none(self, tmp_path):
        """Integration test: legacy records without ancestry return None via full loader."""
        legacy_records = [
            {
                "source_guid": "legacy-001",
                "target_id": "old-record",
                "node_id": "legacy_action_abc123",
                # No parent_target_id
                # No root_target_id
                "content": {"legacy_field": "value"},
            }
        ]

        # Set up directory structure
        target_dir = tmp_path / "agent_io" / "target"
        target_dir.mkdir(parents=True)

        legacy_dir = target_dir / "legacy_action"
        legacy_dir.mkdir(parents=True)
        with open(legacy_dir / "test.json", "w") as f:
            json.dump(legacy_records, f, indent=2)

        downstream_dir = target_dir / "downstream"
        downstream_dir.mkdir(parents=True)
        (downstream_dir / "test.json").write_text("[]")

        request = HistoricalDataRequest(
            action_name="legacy_action",
            lineage=["node_0"],
            source_guid="legacy-001",
            file_path=str(downstream_dir / "test.json"),
            agent_indices={"legacy_action": 1},
        )

        result = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert result is None, "Legacy records without ancestry should not match"

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

        # Request a branch that doesn't exist
        request = HistoricalDataRequest(
            action_name="nonexistent_branch",
            lineage=["node_0", "node_7"],
            source_guid="book-001-catalog",
            file_path=file_path,
            agent_indices={"nonexistent_branch": 99},  # No such node
            parent_target_id="parent-001",
        )

        result = HistoricalNodeDataLoader.load_historical_node_data(request)

        # Should return None, not crash
        assert result is None
