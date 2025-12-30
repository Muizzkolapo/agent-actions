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

FileUDFResult:
    RFC implementation for explicit source mapping. UDFs can return
    FileUDFResult with source_mapping to declare which input(s) produced
    each output, enabling proper lineage for filter, dedup, and merge ops.
"""

import pytest
from typing import Dict, List, Optional

from agent_actions.utilities.lineage.lineage_builder import LineageBuilder
from agent_actions.utilities.field_management.field_manager import FieldManager
from agent_actions.utilities.id_generation.id_generator import IDGenerator
from agent_actions.utilities.udf_management.udf_registry import FileUDFResult


def process_file_level_tool_fixed(
    generated_data, data: List[Dict], source_guid: Optional[str], idx: int = 3
) -> List[Dict]:
    """
    Implementation of the fixed _process_file_level_tool logic.
    Extracted here to avoid circular imports during testing.

    Supports three lineage resolution strategies (in priority order):
    1. FileUDFResult with source_mapping - explicit input->output mapping
    2. Preserved lineage in output - UDF deep-copied records with lineage
    3. Legacy fallback - uses first input record's lineage
    """
    # Handle FileUDFResult wrapper with explicit source mapping
    source_mapping = None
    if isinstance(generated_data, FileUDFResult):
        source_mapping = generated_data.source_mapping
        data_list = generated_data.outputs
    else:
        data_list = generated_data if isinstance(generated_data, list) else [generated_data]

    # Fallback source for records without preserved lineage
    fallback_source = data[0] if data else {}

    base_node_id = IDGenerator.generate_node_id(idx)
    tracked_data = []
    field_manager = FieldManager()

    for i, item in enumerate(data_list):
        if isinstance(item, dict):
            item_copy = item.copy()
            item_copy = field_manager.ensure_required_fields(item_copy, source_guid, idx)
            node_id = f"{base_node_id}_{i}"

            # Priority 1: Explicit source_mapping from FileUDFResult
            if source_mapping is not None and i in source_mapping:
                source_idx = source_mapping[i]

                if isinstance(source_idx, list):
                    # Many-to-one: multiple inputs merged into one output
                    source_items = [data[j] for j in source_idx if j < len(data)]
                    item_copy = LineageBuilder.add_lineage_tracking_from_sources(
                        item_copy, source_items, node_id
                    )
                else:
                    # One-to-one: single input mapped to output
                    source_item = data[source_idx] if source_idx < len(data) else fallback_source
                    item_copy = LineageBuilder.add_lineage_tracking(item_copy, source_item, node_id)

            # Priority 2: Preserved lineage in output (UDF deep-copied records)
            elif "lineage" in item and isinstance(item["lineage"], list):
                item_copy = LineageBuilder.add_lineage_tracking(item_copy, item, node_id)

            # Priority 3: Legacy fallback to first input
            else:
                item_copy = LineageBuilder.add_lineage_tracking(item_copy, fallback_source, node_id)

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


class TestFileUDFResult:
    """Tests for FileUDFResult dataclass and validation."""

    def test_file_udf_result_basic_creation(self):
        """Test basic FileUDFResult creation."""
        result = FileUDFResult(
            outputs=[{"a": 1}, {"b": 2}], source_mapping={0: 0, 1: 1}, input_count=2
        )

        assert len(result.outputs) == 2
        assert result.source_mapping == {0: 0, 1: 1}
        assert result.input_count == 2

    def test_file_udf_result_without_mapping(self):
        """Test FileUDFResult without source_mapping."""
        result = FileUDFResult(outputs=[{"a": 1}])

        assert len(result.outputs) == 1
        assert result.source_mapping is None
        assert result.input_count is None

    def test_file_udf_result_with_many_to_one_mapping(self):
        """Test FileUDFResult with many-to-one mapping."""
        result = FileUDFResult(
            outputs=[{"merged": "abc"}], source_mapping={0: [0, 1, 2]}, input_count=3
        )

        assert result.source_mapping[0] == [0, 1, 2]

    def test_file_udf_result_validates_output_index_bounds(self):
        """Test that output index out of bounds raises error."""
        with pytest.raises(ValueError, match="out of bounds for outputs"):
            FileUDFResult(
                outputs=[{"a": 1}],
                source_mapping={5: 0},  # 5 is out of bounds
                input_count=1,
            )

    def test_file_udf_result_validates_input_index_bounds(self):
        """Test that input index out of bounds raises error."""
        with pytest.raises(ValueError, match="out of bounds for inputs"):
            FileUDFResult(
                outputs=[{"a": 1}],
                source_mapping={0: 10},  # 10 is out of bounds
                input_count=2,
            )

    def test_file_udf_result_validates_list_input_indices(self):
        """Test that list input indices are validated."""
        with pytest.raises(ValueError, match="out of bounds for inputs"):
            FileUDFResult(
                outputs=[{"a": 1}],
                source_mapping={0: [0, 1, 99]},  # 99 is out of bounds
                input_count=3,
            )

    def test_file_udf_result_skips_validation_without_input_count(self):
        """Test that input validation is skipped when input_count not provided."""
        # Should not raise even with seemingly invalid mapping
        result = FileUDFResult(
            outputs=[{"a": 1}],
            source_mapping={0: 999},  # Would be invalid if input_count provided
        )
        assert result.source_mapping[0] == 999


class TestFileUDFResultLineageTracking:
    """Tests for FileUDFResult lineage tracking integration."""

    def test_one_to_one_source_mapping(self):
        """Test one-to-one source mapping with explicit indices."""
        # Input data: 3 records with unique lineages
        input_data = [
            {
                "node_id": "node_2_a_0",
                "lineage": ["node_0", "node_1", "node_2_a_0"],
                "content": "A",
            },
            {
                "node_id": "node_2_b_0",
                "lineage": ["node_0", "node_1", "node_2_b_0"],
                "content": "B",
            },
            {
                "node_id": "node_2_c_0",
                "lineage": ["node_0", "node_1", "node_2_c_0"],
                "content": "C",
            },
        ]

        # UDF returns 2 outputs, mapping output 0 -> input 0, output 1 -> input 2
        # (skipped input 1 during dedup)
        udf_output = FileUDFResult(
            outputs=[{"content": "Processed A"}, {"content": "Processed C"}],
            source_mapping={0: 0, 1: 2},
            input_count=3,
        )

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-guid"
        )

        assert len(result) == 2

        # Output 0 should have lineage from input 0 (node_2_a_0)
        assert "node_2_a_0" in result[0]["lineage"]
        assert result[0]["lineage"][-2] == "node_2_a_0"

        # Output 1 should have lineage from input 2 (node_2_c_0)
        assert "node_2_c_0" in result[1]["lineage"]
        assert result[1]["lineage"][-2] == "node_2_c_0"

    def test_many_to_one_source_mapping(self):
        """Test many-to-one mapping creates lineage_sources."""
        # Input data: 3 records that will be merged
        input_data = [
            {
                "node_id": "node_2_a_0",
                "lineage": ["node_0", "node_1", "node_2_a_0"],
                "content": "A",
            },
            {
                "node_id": "node_2_b_0",
                "lineage": ["node_0", "node_1", "node_2_b_0"],
                "content": "B",
            },
            {
                "node_id": "node_2_c_0",
                "lineage": ["node_0", "node_1", "node_2_c_0"],
                "content": "C",
            },
        ]

        # UDF merges all 3 inputs into 1 output
        udf_output = FileUDFResult(
            outputs=[{"content": "Merged ABC"}],
            source_mapping={0: [0, 1, 2]},  # Output 0 from inputs 0, 1, 2
            input_count=3,
        )

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-guid"
        )

        assert len(result) == 1

        # Should have primary lineage from first source
        assert "node_2_a_0" in result[0]["lineage"]

        # Should have lineage_sources field with all parent node_ids
        assert "lineage_sources" in result[0]
        lineage_sources = result[0]["lineage_sources"]
        assert "node_2_a_0" in lineage_sources
        assert "node_2_b_0" in lineage_sources
        assert "node_2_c_0" in lineage_sources

    def test_file_udf_result_without_mapping_falls_back(self):
        """Test that FileUDFResult without mapping falls back to existing behavior."""
        input_data = [
            {
                "node_id": "node_2_a_0",
                "lineage": ["node_0", "node_1", "node_2_a_0"],
                "content": "A",
            },
            {
                "node_id": "node_2_b_0",
                "lineage": ["node_0", "node_1", "node_2_b_0"],
                "content": "B",
            },
        ]

        # FileUDFResult without source_mapping
        udf_output = FileUDFResult(outputs=[{"content": "Output without mapping"}])

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-guid"
        )

        assert len(result) == 1
        # Should fall back to first input's lineage (legacy behavior)
        assert "node_2_a_0" in result[0]["lineage"]

    def test_mixed_mapping_some_explicit_some_fallback(self):
        """Test when source_mapping only covers some outputs."""
        input_data = [
            {"node_id": "node_2_a_0", "lineage": ["node_0", "node_2_a_0"], "content": "A"},
            {"node_id": "node_2_b_0", "lineage": ["node_0", "node_2_b_0"], "content": "B"},
        ]

        # Only map output 0, output 1 has no mapping
        udf_output = FileUDFResult(
            outputs=[{"content": "Mapped"}, {"content": "Unmapped"}],
            source_mapping={0: 1},  # Only output 0 is mapped (to input 1)
            input_count=2,
        )

        result = process_file_level_tool_fixed(
            generated_data=udf_output, data=input_data, source_guid="test-guid"
        )

        assert len(result) == 2

        # Output 0 should use explicit mapping (input 1 -> node_2_b_0)
        assert "node_2_b_0" in result[0]["lineage"]

        # Output 1 should fall back to first input (node_2_a_0)
        assert "node_2_a_0" in result[1]["lineage"]


class TestLineageBuilderFromSources:
    """Tests for LineageBuilder.add_lineage_tracking_from_sources."""

    def test_single_source_no_lineage_sources_field(self):
        """Test that single source doesn't create lineage_sources field."""
        obj = {"content": "test"}
        source_items = [{"node_id": "node_1", "lineage": ["node_0", "node_1"]}]

        result = LineageBuilder.add_lineage_tracking_from_sources(obj, source_items, "node_2")

        assert "lineage_sources" not in result
        assert result["lineage"] == ["node_0", "node_1", "node_2"]

    def test_multiple_sources_creates_lineage_sources(self):
        """Test that multiple sources create lineage_sources field."""
        obj = {"content": "merged"}
        source_items = [
            {"node_id": "node_1_a", "lineage": ["node_0", "node_1_a"]},
            {"node_id": "node_1_b", "lineage": ["node_0", "node_1_b"]},
            {"node_id": "node_1_c", "lineage": ["node_0", "node_1_c"]},
        ]

        result = LineageBuilder.add_lineage_tracking_from_sources(obj, source_items, "node_2")

        # Primary lineage from first source
        assert result["lineage"] == ["node_0", "node_1_a", "node_2"]

        # All parent node_ids in lineage_sources
        assert "lineage_sources" in result
        assert result["lineage_sources"] == ["node_1_a", "node_1_b", "node_1_c"]

    def test_empty_sources_creates_minimal_lineage(self):
        """Test that empty sources creates minimal lineage."""
        obj = {"content": "orphan"}

        result = LineageBuilder.add_lineage_tracking_from_sources(obj, [], "node_1")

        assert result["lineage"] == ["node_1"]
        assert "lineage_sources" not in result

    def test_sources_without_lineage(self):
        """Test handling sources that don't have lineage field."""
        obj = {"content": "test"}
        source_items = [
            {"content": "no lineage 1"},
            {"content": "no lineage 2"},
        ]

        result = LineageBuilder.add_lineage_tracking_from_sources(obj, source_items, "node_1")

        # Should have minimal lineage (just new node)
        assert result["lineage"] == ["node_1"]
        # lineage_sources should be empty or not present
        assert result.get("lineage_sources", []) == []
