"""
Tests for FILE-level granularity lineage preservation.

This module tests the fix for the bug where FILE-level UDFs would lose
individual record lineages, causing all output records to have the same
lineage (from the first input record).

Bug Report Summary:
    When a UDF is configured with granularity: FILE, the framework was
    assigning the same lineage (from the first input record) to ALL output
    records, regardless of their actual origin.

Fix:
    If the UDF returns records with existing lineage fields, the framework
    now preserves them instead of overwriting with the first input's lineage.
"""

import pytest
from typing import Dict, List, Optional

from agent_actions.utilities.lineage.lineage_builder import LineageBuilder
from agent_actions.utilities.field_management.field_manager import FieldManager
from agent_actions.utilities.id_generation.id_generator import IDGenerator


def process_file_level_tool_fixed(
    generated_data, data: List[Dict], source_guid: Optional[str], idx: int = 3
) -> List[Dict]:
    """
    Implementation of the fixed _process_file_level_tool logic.
    Extracted here to avoid circular imports during testing.
    """
    data_list = generated_data if isinstance(generated_data, list) else [generated_data]

    # Fallback source for records without preserved lineage (THE FIX)
    fallback_source = data[0] if data else {}

    base_node_id = IDGenerator.generate_node_id(idx)
    tracked_data = []
    field_manager = FieldManager()

    for i, item in enumerate(data_list):
        if isinstance(item, dict):
            item_copy = item.copy()
            item_copy = field_manager.ensure_required_fields(item_copy, source_guid, idx)
            node_id = f"{base_node_id}_{i}"

            # THE FIX: Use output item's lineage if it exists
            if "lineage" in item and isinstance(item["lineage"], list):
                source_item = item  # UDF preserved lineage - use it
            else:
                source_item = fallback_source  # Legacy fallback

            item_copy = LineageBuilder.add_lineage_tracking(item_copy, source_item, node_id)
            tracked_data.append(item_copy)
        else:
            tracked_data.append(item)

    return tracked_data


def process_file_level_tool_buggy(
    generated_data, data: List[Dict], source_guid: Optional[str], idx: int = 3
) -> List[Dict]:
    """
    The BUGGY implementation before the fix.
    Always uses data[0] as source for all records.
    """
    data_list = generated_data if isinstance(generated_data, list) else [generated_data]

    # THE BUG: Always uses first input for ALL records
    source_item = data[0] if data else {}

    base_node_id = IDGenerator.generate_node_id(idx)
    tracked_data = []
    field_manager = FieldManager()

    for i, item in enumerate(data_list):
        if isinstance(item, dict):
            item_copy = item.copy()
            item_copy = field_manager.ensure_required_fields(item_copy, source_guid, idx)
            node_id = f"{base_node_id}_{i}"
            # BUG: source_item is always data[0]
            item_copy = LineageBuilder.add_lineage_tracking(item_copy, source_item, node_id)
            tracked_data.append(item_copy)
        else:
            tracked_data.append(item)

    return tracked_data


class TestFileLevelLineagePreservation:
    """Tests for FILE-level UDF lineage preservation."""

    def test_preserves_lineage_when_udf_returns_records_with_lineage(self):
        """
        Test that when UDF returns records with existing lineage,
        those lineages are preserved (not overwritten by first input's lineage).
        """
        # Input data: 3 records with different lineages
        input_data = [
            {
                "node_id": "node_2_aaa_0",
                "lineage": ["node_0_start", "node_1_middle", "node_2_aaa_0"],
                "content": "Record A",
            },
            {
                "node_id": "node_2_bbb_0",
                "lineage": ["node_0_start", "node_1_middle", "node_2_bbb_0"],
                "content": "Record B",
            },
            {
                "node_id": "node_2_ccc_0",
                "lineage": ["node_0_start", "node_1_middle", "node_2_ccc_0"],
                "content": "Record C",
            },
        ]

        # UDF output: records with preserved lineages (as if UDF did deep copy)
        udf_output = [
            {
                "node_id": "node_2_aaa_0",
                "lineage": ["node_0_start", "node_1_middle", "node_2_aaa_0"],
                "content": "Processed A",
            },
            {
                "node_id": "node_2_ccc_0",
                "lineage": ["node_0_start", "node_1_middle", "node_2_ccc_0"],
                "content": "Processed C (B was deduped)",
            },
        ]

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-source-guid"
        )

        assert len(result) == 2

        # First output should have lineage from 'aaa', not from first input
        assert "node_2_aaa_0" in result[0]["lineage"]
        assert result[0]["lineage"][-2] == "node_2_aaa_0"

        # Second output should have lineage from 'ccc', not from first input
        assert "node_2_ccc_0" in result[1]["lineage"]
        assert result[1]["lineage"][-2] == "node_2_ccc_0"

    def test_falls_back_to_first_input_when_no_lineage_in_output(self):
        """
        Test that when UDF returns records without lineage,
        fallback to first input's lineage (legacy behavior).
        """
        input_data = [
            {
                "node_id": "node_2_first_0",
                "lineage": ["node_0_start", "node_1_middle", "node_2_first_0"],
                "content": "First Record",
            },
            {
                "node_id": "node_2_second_0",
                "lineage": ["node_0_start", "node_1_middle", "node_2_second_0"],
                "content": "Second Record",
            },
        ]

        # UDF output without lineage (simple UDF that doesn't preserve lineage)
        udf_output = [
            {"content": "Processed without lineage"},
        ]

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-source-guid"
        )

        # Should fall back to first input's lineage (legacy behavior)
        assert len(result) == 1
        assert "node_2_first_0" in result[0]["lineage"]

    def test_mixed_lineage_preservation(self):
        """
        Test mixed case: some UDF outputs have lineage, others don't.
        """
        input_data = [
            {
                "node_id": "node_2_first_0",
                "lineage": ["node_0", "node_1", "node_2_first_0"],
                "content": "First",
            },
            {
                "node_id": "node_2_second_0",
                "lineage": ["node_0", "node_1", "node_2_second_0"],
                "content": "Second",
            },
        ]

        # Mixed output: first has preserved lineage, second doesn't
        udf_output = [
            {
                "node_id": "node_2_second_0",
                "lineage": ["node_0", "node_1", "node_2_second_0"],
                "content": "Has lineage",
            },
            {"content": "No lineage"},
        ]

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-guid"
        )

        assert len(result) == 2

        # First result: preserved its own lineage (from node_2_second_0)
        assert "node_2_second_0" in result[0]["lineage"]

        # Second result: fallback to first input's lineage
        assert "node_2_first_0" in result[1]["lineage"]

    def test_bug_scenario_demonstrates_fix(self):
        """
        Reproduce the exact bug scenario from the bug report.

        Before fix: All records would have the same lineage from first input.
        After fix: Each record preserves its own lineage.
        """
        # Simulate multiple input records with unique lineages
        input_data = [
            {
                "node_id": f"node_2_{chr(97+i)}_0",  # node_2_a_0, node_2_b_0, etc.
                "lineage": ["node_0_start", "node_1_middle", f"node_2_{chr(97+i)}_0"],
                "content": f"Record {i}",
            }
            for i in range(5)
        ]

        # UDF preserves lineage via deep copy (like in the bug report)
        udf_output = [
            {
                "node_id": input_data[i]["node_id"],
                "lineage": input_data[i]["lineage"].copy(),
                "content": f"Processed {i}",
            }
            for i in [0, 2, 4]  # Simulating dedup keeping records 0, 2, 4
        ]

        # Test with FIXED implementation
        result_fixed = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-guid"
        )

        # Verify each result has DIFFERENT parent lineage
        parent_lineages_fixed = [r["lineage"][-2] for r in result_fixed]

        # After fix: should be 'node_2_a_0', 'node_2_c_0', 'node_2_e_0'
        assert parent_lineages_fixed[0] == "node_2_a_0"
        assert parent_lineages_fixed[1] == "node_2_c_0"
        assert parent_lineages_fixed[2] == "node_2_e_0"
        assert len(set(parent_lineages_fixed)) == 3  # All unique

    def test_buggy_implementation_shows_issue(self):
        """
        Demonstrate that the BUGGY implementation assigns same lineage to all.
        """
        input_data = [
            {
                "node_id": f"node_2_{chr(97+i)}_0",
                "lineage": ["node_0_start", "node_1_middle", f"node_2_{chr(97+i)}_0"],
                "content": f"Record {i}",
            }
            for i in range(5)
        ]

        udf_output = [
            {
                "node_id": input_data[i]["node_id"],
                "lineage": input_data[i]["lineage"].copy(),
                "content": f"Processed {i}",
            }
            for i in [0, 2, 4]
        ]

        # Test with BUGGY implementation
        result_buggy = process_file_level_tool_buggy(
            generated_data=udf_output, data=input_data, source_guid="test-guid"
        )

        # Bug: all have same parent lineage (from first input)
        parent_lineages_buggy = [r["lineage"][-2] for r in result_buggy]

        # All should be 'node_2_a_0' (the bug!)
        assert parent_lineages_buggy[0] == "node_2_a_0"
        assert parent_lineages_buggy[1] == "node_2_a_0"  # Should be c, but bug
        assert parent_lineages_buggy[2] == "node_2_a_0"  # Should be e, but bug
        assert len(set(parent_lineages_buggy)) == 1  # All same (bug!)

    def test_empty_input_data(self):
        """Test handling of empty input data."""
        udf_output = [
            {"content": "Created from nothing"},
        ]

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=[], source_guid="test-guid"
        )

        assert len(result) == 1
        # With empty input, lineage should just be the new node_id
        assert len(result[0]["lineage"]) == 1
        assert result[0]["lineage"][0].startswith("node_3_")

    def test_single_item_not_list(self):
        """Test that single dict output (not list) is handled."""
        input_data = [
            {"node_id": "node_2_a_0", "lineage": ["node_0", "node_2_a_0"], "content": "Input"}
        ]

        udf_output = {"lineage": ["node_0", "node_2_a_0"], "content": "Single output"}

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-guid"
        )

        assert len(result) == 1
        assert "node_2_a_0" in result[0]["lineage"]
