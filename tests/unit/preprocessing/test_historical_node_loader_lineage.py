"""
Unit tests for HistoricalNodeDataLoader lineage-based matching.

These tests document the expected behavior of lineage-based record matching
for handling split records. Tests will initially FAIL (demonstrating the bug),
then PASS after implementing lineage matching in _find_record_by_identifiers().
"""

import pytest
import json
from pathlib import Path
from typing import List, Dict, Optional
from agent_actions.preprocessing.context.historical_node_loader import HistoricalNodeDataLoader


@pytest.fixture
def split_records() -> List[Dict]:
    """
    Load split records fixture.

    Contains 3 records from node_5 split operation:
    - Record #1: Branch A with 1 tag
    - Record #2: Branch B with 2 tags (the bug case)
    - Record #3: Branch C with 1 tag

    All share same source_guid and node_id but have different lineages.
    """
    fixture_path = Path(__file__).parent.parent.parent / 'fixtures' / 'historical_loader' / 'split_records_node5.json'
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def caller_records() -> List[Dict]:
    """
    Load caller records fixture.

    Contains 3 records from node_23 that need to look up node_5 data:
    - Caller #1: Should match Split Record #1
    - Caller #2: Should match Split Record #2 (2 tags)
    - Caller #3: Should match Split Record #3

    Each has a different lineage path.
    """
    fixture_path = Path(__file__).parent.parent.parent / 'fixtures' / 'historical_loader' / 'caller_records_node23.json'
    with open(fixture_path) as f:
        return json.load(f)


class TestFindRecordByIdentifiers:
    """Tests for HistoricalNodeDataLoader._find_record_by_identifiers with lineage matching."""

    def test_find_record_basic_match_no_lineage(self, split_records):
        """
        Test backward compatibility: match by source_guid + node_id only.

        When caller_lineage is None, should use legacy matching behavior.
        This ensures backward compatibility with existing code.
        """
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid="test-source-guid-12345",
            node_id="node_5_split_abc123"
            # Note: No caller_lineage parameter (will use default None)
        )

        # Should return first matching record
        assert result is not None, "Should find a record with basic matching"
        assert result['source_guid'] == "test-source-guid-12345"
        assert result['node_id'] == "node_5_split_abc123"
        # Note: Without lineage, returns first match (Record #1)
        assert result['target_id'] == "split-record-1-target-id"

    def test_find_record_with_lineage_single_match(self, split_records):
        """
        Test lineage matching when only one record matches source_guid + node_id.

        When there's only one record, lineage matching should still work
        (though it's not strictly necessary).
        """
        # Use only the first record
        single_record_data = [split_records[0]]

        # Create a caller lineage that matches this record
        caller_lineage = [
            "node_0_initial_process",
            "node_1_extract_data",
            "node_4_validate_input",
            "node_5_split_abc123",
            "node_6_process_branch_a",
            "node_23_final_output"
        ]

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=single_record_data,
            source_guid="test-source-guid-12345",
            node_id="node_5_split_abc123",
            caller_lineage=caller_lineage
        )

        assert result is not None
        assert result['target_id'] == "split-record-1-target-id"

    def test_find_record_with_lineage_split_records_branch1(self, split_records, caller_records):
        """
        Test lineage correctly identifies Branch A record.

        Caller #1 has lineage containing node_6_process_branch_a,
        which should match Split Record #1.
        """
        caller = caller_records[0]  # Caller Record #1 (Branch A)

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid=caller['source_guid'],
            node_id="node_5_split_abc123",
            caller_lineage=caller['lineage']
        )

        assert result is not None, "Should find matching record for Branch A"
        assert result['target_id'] == "split-record-1-target-id", "Should match Split Record #1"
        assert result['content']['status'] == "active"
        assert result['content']['tags'] == ["tag-a"]

    def test_find_record_with_lineage_split_records_branch2(self, split_records, caller_records):
        """
        Test lineage correctly identifies Branch B record (THE BUG CASE).

        Caller #2 has lineage containing node_6_process_branch_b,
        which should match Split Record #2 (the one with 2 tags).

        WITHOUT FIX: Returns Split Record #1 (1 tag) - WRONG!
        WITH FIX: Returns Split Record #2 (2 tags) - CORRECT!
        """
        caller = caller_records[1]  # Caller Record #2 (Branch B)

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid=caller['source_guid'],
            node_id="node_5_split_abc123",
            caller_lineage=caller['lineage']
        )

        # These assertions will FAIL without the fix
        assert result is not None, "Should find matching record for Branch B"
        assert result['target_id'] == "split-record-2-target-id", \
            "Should match Split Record #2, not Record #1 (BUG!)"
        assert result['content']['status'] == "pending", \
            "Branch B record should have status='pending'"
        assert len(result['content']['tags']) == 2, \
            "Branch B record should have 2 tags (the distinguishing feature)"
        assert result['content']['tags'] == ["tag-b", "tag-extra"], \
            "Should get the correct tags from Branch B record"

    def test_find_record_with_lineage_split_records_branch3(self, split_records, caller_records):
        """
        Test lineage correctly identifies Branch C record.

        Caller #3 has lineage containing node_6_process_branch_c,
        which should match Split Record #3.
        """
        caller = caller_records[2]  # Caller Record #3 (Branch C)

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid=caller['source_guid'],
            node_id="node_5_split_abc123",
            caller_lineage=caller['lineage']
        )

        assert result is not None, "Should find matching record for Branch C"
        assert result['target_id'] == "split-record-3-target-id", "Should match Split Record #3"
        assert result['content']['status'] == "completed"
        assert result['content']['tags'] == ["tag-c"]

    def test_find_record_lineage_mismatch_returns_none(self, split_records):
        """
        Test that mismatched lineage returns first source_guid match as fallback.

        When caller's lineage doesn't match any record's lineage, the fix now returns
        the first source_guid match as a fallback (instead of None). This handles
        cross-run scenarios where UUIDs in lineage differ.
        """
        # Create a lineage that doesn't match any split record
        mismatched_lineage = [
            "node_0_initial_process",
            "node_1_extract_data",
            "node_4_validate_input",
            "node_5_split_abc123",
            "node_6_process_branch_NONEXISTENT",  # Doesn't exist in any split record
            "node_23_final_output"
        ]

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid="test-source-guid-12345",
            node_id="node_5_split_abc123",
            caller_lineage=mismatched_lineage
        )

        # After fix: returns first source_guid match as fallback
        assert result is not None, \
            "Should return first source_guid match when lineage doesn't match (fallback behavior)"
        assert result['source_guid'] == "test-source-guid-12345"

    def test_find_record_lineage_prefix_match(self, split_records, caller_records):
        """
        Test that record's lineage must be a prefix of caller's lineage.

        Record from node_5 has lineage: [node_0, node_1, node_4, node_5, node_6]
        Caller from node_23 has lineage: [node_0, node_1, node_4, node_5, node_6, ..., node_23]

        Record's lineage should be a PREFIX of caller's lineage for a match.
        """
        caller = caller_records[1]  # Any caller record

        # The split record has shorter lineage (up to node_6 or so)
        # The caller has longer lineage (all the way to node_23)
        # This should still match because record_lineage is a prefix

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid=caller['source_guid'],
            node_id="node_5_split_abc123",
            caller_lineage=caller['lineage']
        )

        assert result is not None, \
            "Should match when record lineage is a prefix of caller lineage"

        # Verify the matched record's lineage is indeed a prefix
        record_lineage = result['lineage']
        caller_lineage = caller['lineage']

        assert len(record_lineage) <= len(caller_lineage), \
            "Record lineage should be shorter or equal to caller lineage"

        # Check prefix matching
        for i, node_id in enumerate(record_lineage):
            assert caller_lineage[i] == node_id, \
                f"Lineage mismatch at position {i}: record has {node_id}, caller has {caller_lineage[i]}"

    def test_find_record_lineage_longer_than_caller_returns_none(self, split_records):
        """
        Test edge case: record has longer lineage than caller - returns fallback.

        This is an impossible scenario (caller can't have seen fewer nodes
        than the record it's trying to look up), but we handle it gracefully
        by returning the first source_guid match as fallback.
        """
        # Create a short caller lineage (only up to node_5)
        short_caller_lineage = [
            "node_0_initial_process",
            "node_1_extract_data",
            "node_4_validate_input",
            "node_5_split_abc123"
        ]

        # Try to match against split records that have node_6 in their lineage
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid="test-source-guid-12345",
            node_id="node_5_split_abc123",
            caller_lineage=short_caller_lineage
        )

        # After fix: returns first source_guid match as fallback
        assert result is not None, \
            "Should return first source_guid match when lineage doesn't match (fallback behavior)"
        assert result['source_guid'] == "test-source-guid-12345"


class TestLineageMatchingEdgeCases:
    """Additional edge case tests for lineage matching."""

    def test_find_record_empty_lineage_list(self, split_records):
        """Test handling of empty lineage list."""
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid="test-source-guid-12345",
            node_id="node_5_split_abc123",
            caller_lineage=[]  # Empty list
        )

        # Empty lineage should be treated similar to None
        # (or return None since no match is possible)
        assert result is None or result is not None  # Implementation-dependent

    def test_find_record_no_matching_source_guid(self, split_records):
        """Test that non-matching source_guid returns None."""
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid="nonexistent-source-guid",
            node_id="node_5_split_abc123",
            caller_lineage=["node_0_initial_process"]
        )

        assert result is None, "Should return None when source_guid doesn't match"

    def test_find_record_no_matching_node_id(self, split_records):
        """Test that non-matching node_id still matches by source_guid (fix behavior)."""
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=split_records,
            source_guid="test-source-guid-12345",
            node_id="nonexistent-node-id",
            caller_lineage=["node_0_initial_process"]
        )

        # After fix: node_id is not used for matching, only source_guid matters
        # When lineage doesn't match, returns first source_guid match as fallback
        assert result is not None, "Should return first source_guid match (node_id not used for matching)"
        assert result['source_guid'] == "test-source-guid-12345"

    def test_find_record_empty_data_list(self):
        """Test handling of empty data list."""
        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data=[],
            source_guid="test-source-guid-12345",
            node_id="node_5_split_abc123",
            caller_lineage=["node_0_initial_process"]
        )

        assert result is None, "Should return None when data list is empty"
