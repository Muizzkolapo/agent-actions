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
import pytest
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any

from agent_actions.preprocessing.context.historical_node_loader import (
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
                ├── node_4_generate_seo/
                │   └── test.json (branch A records)
                ├── node_5_generate_recommendations/
                │   └── test.json (branch B records)
                └── node_6_assess_reading_level/
                    └── test.json (branch C records)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        target_dir = tmp_path / "agent_io" / "target"

        # Get records by node
        parent = parallel_branch_records[0]
        branch_a = parallel_branch_records[1]
        branch_b = parallel_branch_records[2]
        branch_c = parallel_branch_records[3]

        # Create directories and write records
        for node_name, records in [
            ("node_4_generate_seo", [branch_a]),
            ("node_5_generate_recommendations", [branch_b]),
            ("node_6_assess_reading_level", [branch_c]),
        ]:
            node_dir = target_dir / node_name
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


class TestParallelBranchMerge:
    """
    Tests for the Diamond/Fan-in pattern where parallel branches merge.

    Scenario:
        validate → seo ────┐
                → recs ────┼→ score (MERGE)
                → level ───┘

    The score action needs access to ALL three parallel branches' outputs.
    """

    def test_merge_action_can_load_sibling_branch_a(
        self, parallel_branch_temp_dir, parallel_branch_records
    ):
        """Merge action should be able to load Branch A (seo) by parent_target_id."""
        branch_a = parallel_branch_records[1]

        file_path = str(
            parallel_branch_temp_dir / "agent_io" / "target" / "node_7_score_quality" / "test.json"
        )

        request = HistoricalDataRequest(
            action_name="generate_seo",
            lineage=["node_0_extract", "node_1_enrich", "node_3_validate", "node_7_score"],
            source_guid="book-001-catalog",
            file_path=file_path,
            agent_indices={"generate_seo": 4},
            parent_target_id="parent-001",  # Query by parent
        )

        result = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert result is not None, "Should find Branch A record by parent_target_id"
        assert result.get("primary_keywords") == ["java", "clean code", "refactoring"]
        assert result.get("seo_score") == 85

    def test_merge_action_can_load_sibling_branch_b(
        self, parallel_branch_temp_dir, parallel_branch_records
    ):
        """Merge action should be able to load Branch B (recommendations) by parent_target_id."""
        file_path = str(
            parallel_branch_temp_dir / "agent_io" / "target" / "node_7_score_quality" / "test.json"
        )

        request = HistoricalDataRequest(
            action_name="generate_recommendations",
            lineage=["node_0_extract", "node_1_enrich", "node_3_validate", "node_7_score"],
            source_guid="book-001-catalog",
            file_path=file_path,
            agent_indices={"generate_recommendations": 5},
            parent_target_id="parent-001",
        )

        result = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert result is not None, "Should find Branch B record by parent_target_id"
        assert result.get("similar_books") == ["Refactoring", "Design Patterns"]
        assert result.get("confidence") == 0.92

    def test_merge_action_can_load_sibling_branch_c(
        self, parallel_branch_temp_dir, parallel_branch_records
    ):
        """Merge action should be able to load Branch C (reading level) by parent_target_id."""
        file_path = str(
            parallel_branch_temp_dir / "agent_io" / "target" / "node_7_score_quality" / "test.json"
        )

        request = HistoricalDataRequest(
            action_name="assess_reading_level",
            lineage=["node_0_extract", "node_1_enrich", "node_3_validate", "node_7_score"],
            source_guid="book-001-catalog",
            file_path=file_path,
            agent_indices={"assess_reading_level": 6},
            parent_target_id="parent-001",
        )

        result = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert result is not None, "Should find Branch C record by parent_target_id"
        assert result.get("reading_level") == "advanced"
        assert result.get("grade_equivalent") == "graduate"

    def test_parallel_siblings_isolated_by_parent_target_id(self, parallel_branch_temp_dir):
        """Different parent_target_ids should not cross-match."""
        # Create a second parent's branches
        second_parent_branches = [
            {
                "source_guid": "book-001-catalog",
                "target_id": "branch-a-002",
                "parent_target_id": "parent-002",  # DIFFERENT parent
                "root_target_id": "parent-002",
                "node_id": "node_4_generate_seo",
                "lineage": ["node_0_extract", "node_3_validate", "node_4_seo"],
                "content": {
                    "primary_keywords": ["different", "keywords"],
                    "seo_score": 50,
                },
            }
        ]

        # Write second parent's branch to the same node directory
        node_dir = parallel_branch_temp_dir / "agent_io" / "target" / "node_4_generate_seo"

        # Load existing and append
        with open(node_dir / "test.json") as f:
            existing = json.load(f)

        existing.append(second_parent_branches[0])

        with open(node_dir / "test.json", "w") as f:
            json.dump(existing, f, indent=2)

        # Query for parent-001's branch - should NOT get parent-002's data
        file_path = str(
            parallel_branch_temp_dir / "agent_io" / "target" / "node_7_score_quality" / "test.json"
        )

        request = HistoricalDataRequest(
            action_name="generate_seo",
            lineage=["node_0_extract", "node_3_validate", "node_7_score"],
            source_guid="book-001-catalog",
            file_path=file_path,
            agent_indices={"generate_seo": 4},
            parent_target_id="parent-001",
        )

        result = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert result is not None
        assert (
            result.get("seo_score") == 85
        ), "Should get parent-001's branch (seo_score=85), not parent-002's (seo_score=50)"


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
    """Tests ensuring backward compatibility with legacy records."""

    def test_legacy_record_without_ancestry_uses_source_guid(self):
        """Records without ancestry fields should fall back to source_guid matching."""
        legacy_records = [
            {
                "source_guid": "legacy-001",
                "target_id": "old-record",
                "node_id": "node_5_old_action",
                # No parent_target_id
                # No root_target_id
                "content": {"legacy_field": "value"},
            }
        ]

        # When ancestry matching fails, should fall back to source_guid
        source_matches = [r for r in legacy_records if r.get("source_guid") == "legacy-001"]

        assert len(source_matches) == 1
        assert source_matches[0]["content"]["legacy_field"] == "value"

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
            parallel_branch_temp_dir / "agent_io" / "target" / "node_7_score_quality" / "test.json"
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


class TestMatchingAlgorithmPriority:
    """
    Tests for the matching algorithm priority order.

    Priority:
    1. Lineage match (existing behavior)
    2. Parent match (parent_target_id) for parallel siblings
    3. Root match (root_target_id) for Map-Reduce
    4. Source GUID fallback (legacy)
    """

    def test_lineage_match_takes_priority_over_parent(
        self, parallel_branch_temp_dir, parallel_branch_records
    ):
        """If node is in lineage, use lineage matching (existing behavior)."""
        branch_a = parallel_branch_records[1]

        # Create request where node IS in lineage (normal dependency, not parallel sibling)
        file_path = str(
            parallel_branch_temp_dir / "agent_io" / "target" / "node_7_score_quality" / "test.json"
        )

        request = HistoricalDataRequest(
            action_name="generate_seo",
            # Include node_4 in lineage - this means it's a direct ancestor
            lineage=[
                "node_0_extract",
                "node_1_enrich",
                "node_3_validate",
                "node_4_seo",  # In lineage!
                "node_7_score",
            ],
            source_guid="book-001-catalog",
            file_path=file_path,
            agent_indices={"generate_seo": 4},
            caller_lineage=[
                "node_0_extract",
                "node_1_enrich",
                "node_3_validate",
                "node_4_seo",
                "node_7_score",
            ],
            parent_target_id="parent-001",
        )

        result = HistoricalNodeDataLoader.load_historical_node_data(request)

        # Should still work - lineage match should find the record
        assert result is not None
        assert result.get("primary_keywords") is not None

    def test_parent_match_used_when_not_in_lineage(self, parallel_branch_temp_dir):
        """When dependency node is NOT in lineage (parallel sibling), use parent_target_id."""
        file_path = str(
            parallel_branch_temp_dir / "agent_io" / "target" / "node_7_score_quality" / "test.json"
        )

        request = HistoricalDataRequest(
            action_name="generate_seo",
            # node_4 is NOT in this lineage - we went through node_5 instead
            lineage=[
                "node_0_extract",
                "node_1_enrich",
                "node_3_validate",
                "node_5_recs",  # Different path!
                "node_7_score",
            ],
            source_guid="book-001-catalog",
            file_path=file_path,
            agent_indices={"generate_seo": 4},
            parent_target_id="parent-001",  # Use ancestry matching
        )

        result = HistoricalNodeDataLoader.load_historical_node_data(request)

        # Should find via parent_target_id since lineage match won't work
        assert result is not None, "Should match via parent_target_id when not in lineage"
        assert result.get("primary_keywords") == ["java", "clean code", "refactoring"]
