"""
Integration tests for context scope with split records.

These tests verify that the context scope system (observe, drop, passthrough)
works correctly when historical node data comes from split records that share
the same source_guid and node_id but have different lineages.

Tests the full integration:
    ContextScopeProcessor.build_field_context_with_history()
        → HistoricalNodeDataLoader.load_historical_node_data()
            → _find_record_by_identifiers() with lineage matching
"""

import pytest
import json
import tempfile
from pathlib import Path
from typing import Dict, List
from agent_actions.utilities.context_scope.context_scope_processor import ContextScopeProcessor


@pytest.fixture
def split_records_data():
    """
    Load split records fixture data.

    Returns the 3 split records from node_5 that demonstrate the bug.
    """
    fixture_path = (
        Path(__file__).parent.parent / "fixtures" / "historical_loader" / "split_records_node5.json"
    )
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def caller_records_data():
    """
    Load caller records fixture data.

    Returns the 3 caller records from node_23.
    """
    fixture_path = (
        Path(__file__).parent.parent
        / "fixtures"
        / "historical_loader"
        / "caller_records_node23.json"
    )
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def split_record_temp_dir(split_records_data):
    """
    Create temporary directory structure with split records.

    Structure:
        tmp_dir/
        └── agent_io/
            ├── source/
            │   └── test_file.json (source data)
            └── target/
                └── node_5_split_operation/
                    └── test_file.json (contains 3 split records)

    This mimics the real workflow directory structure where historical
    node data is stored.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        agent_io_dir = tmp_path / "agent_io"

        # Create source directory with source data
        source_dir = agent_io_dir / "source"
        source_dir.mkdir(parents=True)
        source_file = source_dir / "test_file.json"
        with open(source_file, "w") as f:
            json.dump(split_records_data, f, indent=2)

        # Create target directory with split records
        target_dir = agent_io_dir / "target"
        node_5_dir = target_dir / "node_5_split_operation"
        node_5_dir.mkdir(parents=True)

        # Write split records to target file
        split_file = node_5_dir / "test_file.json"
        with open(split_file, "w") as f:
            json.dump(split_records_data, f, indent=2)

        yield tmp_path


@pytest.fixture
def agent_indices_split():
    """
    Agent indices mapping for split record scenario.

    Maps agent names to their node indices for path construction.
    """
    return {
        "initial_process": 0,
        "extract_data": 1,
        "validate_input": 4,
        "split_operation": 5,  # The node that performs the split
        "downstream": 23,  # The node trying to retrieve split data
    }


@pytest.fixture
def dependency_configs_split():
    """
    Dependency configurations for split operation.

    Defines what fields the split_operation outputs.
    """
    return {"split_operation": {"idx": 5, "output": ["status", "tags", "priority"]}}


class TestContextScopeWithSplitRecords:
    """Integration tests for context scope with split record scenarios."""

    def test_build_field_context_loads_branch_a(
        self,
        split_record_temp_dir,
        caller_records_data,
        agent_indices_split,
        dependency_configs_split,
    ):
        """
        Test that field context builder correctly loads Branch A record.

        Caller from Branch A (with node_6_process_branch_a in lineage)
        should retrieve Split Record #1 with 1 tag.
        """
        # Use caller record #1 (Branch A)
        caller = caller_records_data[0]

        # Build agent config
        agent_config = {"idx": 23, "dependencies": ["split_operation"]}

        # Construct file path to current processing location
        # NOTE: Points to downstream node, not historical node
        file_path = str(
            split_record_temp_dir / "agent_io" / "target" / "node_23_downstream" / "test_file.json"
        )

        # Call build_field_context_with_history
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents={},
            agent_name="downstream",
            agent_config=agent_config,
            agent_indices=agent_indices_split,
            dependency_configs=dependency_configs_split,
            current_item=caller,
            file_path=file_path,
        )

        # Assert: Should have loaded split_operation data
        assert "split_operation" in field_context, (
            "Should have loaded split_operation from historical data"
        )

        # Assert: Should have Branch A record (1 tag)
        assert field_context["split_operation"]["status"] == "active", (
            "Branch A record should have status='active'"
        )
        assert field_context["split_operation"]["tags"] == ["tag-a"], (
            "Branch A record should have tags=['tag-a']"
        )

    def test_build_field_context_loads_branch_b(
        self,
        split_record_temp_dir,
        caller_records_data,
        agent_indices_split,
        dependency_configs_split,
    ):
        """
        Test that field context builder correctly loads Branch B record (THE BUG CASE).

        Caller from Branch B (with node_6_process_branch_b in lineage)
        should retrieve Split Record #2 with 2 tags.

        WITHOUT FIX: Will fail - gets Branch A record with 1 tag
        WITH FIX: Will pass - gets Branch B record with 2 tags
        """
        # Use caller record #2 (Branch B)
        caller = caller_records_data[1]

        # Build agent config
        agent_config = {"idx": 23, "dependencies": ["split_operation"]}

        # Construct file path to current processing location
        file_path = str(
            split_record_temp_dir / "agent_io" / "target" / "node_23_downstream" / "test_file.json"
        )

        # Call build_field_context_with_history
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents={},
            agent_name="downstream",
            agent_config=agent_config,
            agent_indices=agent_indices_split,
            dependency_configs=dependency_configs_split,
            current_item=caller,
            file_path=file_path,
        )

        # Assert: Should have loaded split_operation data
        assert "split_operation" in field_context, (
            "Should have loaded split_operation from historical data"
        )

        # THE KEY ASSERTIONS - These will FAIL without the fix
        assert field_context["split_operation"]["status"] == "pending", (
            "Branch B record should have status='pending', not 'active' (BUG!)"
        )

        assert len(field_context["split_operation"]["tags"]) == 2, (
            "Branch B record should have 2 tags, not 1 (THE BUG!)"
        )

        assert field_context["split_operation"]["tags"] == [
            "tag-b",
            "tag-extra",
        ], "Branch B record should have tags=['tag-b', 'tag-extra']"

    def test_build_field_context_loads_branch_c(
        self,
        split_record_temp_dir,
        caller_records_data,
        agent_indices_split,
        dependency_configs_split,
    ):
        """
        Test that field context builder correctly loads Branch C record.

        Caller from Branch C (with node_6_process_branch_c in lineage)
        should retrieve Split Record #3 with 1 tag.
        """
        # Use caller record #3 (Branch C)
        caller = caller_records_data[2]

        # Build agent config
        agent_config = {"idx": 23, "dependencies": ["split_operation"]}

        # Construct file path to current processing location
        file_path = str(
            split_record_temp_dir / "agent_io" / "target" / "node_23_downstream" / "test_file.json"
        )

        # Call build_field_context_with_history
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents={},
            agent_name="downstream",
            agent_config=agent_config,
            agent_indices=agent_indices_split,
            dependency_configs=dependency_configs_split,
            current_item=caller,
            file_path=file_path,
        )

        # Assert: Should have loaded split_operation data
        assert "split_operation" in field_context, (
            "Should have loaded split_operation from historical data"
        )

        # Assert: Should have Branch C record (1 tag)
        assert field_context["split_operation"]["status"] == "completed", (
            "Branch C record should have status='completed'"
        )
        assert field_context["split_operation"]["tags"] == ["tag-c"], (
            "Branch C record should have tags=['tag-c']"
        )

    def test_all_branches_load_unique_data(
        self,
        split_record_temp_dir,
        caller_records_data,
        agent_indices_split,
        dependency_configs_split,
    ):
        """
        Test that all 3 branches load their own unique data, not shared data.

        This is a comprehensive test that verifies each branch gets its own
        correct record and they don't all get the same (first) record.
        """
        agent_config = {"idx": 23, "dependencies": ["split_operation"]}

        file_path = str(
            split_record_temp_dir / "agent_io" / "target" / "node_23_downstream" / "test_file.json"
        )

        loaded_statuses = []
        loaded_tags = []

        # Load field context for all 3 callers
        for i, caller in enumerate(caller_records_data):
            field_context = ContextScopeProcessor.build_field_context_with_history(
                contents={},
                agent_name="downstream",
                agent_config=agent_config,
                agent_indices=agent_indices_split,
                dependency_configs=dependency_configs_split,
                current_item=caller,
                file_path=file_path,
            )

            assert "split_operation" in field_context, (
                f"Caller {i + 1} should have loaded split_operation data"
            )

            loaded_statuses.append(field_context["split_operation"]["status"])
            loaded_tags.append(tuple(field_context["split_operation"]["tags"]))

        # Assert: All 3 branches should have DIFFERENT data
        # Without the fix, all would have the same status/tags (from first record)
        assert len(set(loaded_statuses)) == 3, (
            f"All 3 branches should have unique statuses, got: {loaded_statuses}"
        )

        # Assert: Specific expected values
        assert "active" in loaded_statuses, "Branch A status should be present"
        assert "pending" in loaded_statuses, "Branch B status should be present"
        assert "completed" in loaded_statuses, "Branch C status should be present"

        # Assert: Branch B should have 2 tags (the distinguishing feature)
        tag_lengths = [len(tags) for tags in loaded_tags]
        assert 2 in tag_lengths, (
            "One branch should have 2 tags (Branch B), got tag lengths: " + str(tag_lengths)
        )


class TestContextScopeSplitRecordsEdgeCases:
    """Edge case tests for context scope with split records."""

    def test_missing_lineage_in_current_item(
        self, split_record_temp_dir, agent_indices_split, dependency_configs_split
    ):
        """
        Test handling when current_item has no lineage.

        Should gracefully handle (possibly returning None or first match).
        """
        # Current item WITHOUT lineage
        current_item = {
            "source_guid": "test-source-guid-12345",
            "node_id": "node_23_downstream",
            "content": {},
            # NOTE: No lineage field
        }

        agent_config = {"idx": 23, "dependencies": ["split_operation"]}

        file_path = str(
            split_record_temp_dir / "agent_io" / "target" / "node_23_downstream" / "test_file.json"
        )

        # Should not crash
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents={},
            agent_name="downstream",
            agent_config=agent_config,
            agent_indices=agent_indices_split,
            dependency_configs=dependency_configs_split,
            current_item=current_item,
            file_path=file_path,
        )

        # May or may not have loaded split_operation (implementation-dependent)
        # Just verify it doesn't crash

    def test_wrong_source_guid_returns_none(
        self,
        split_record_temp_dir,
        caller_records_data,
        agent_indices_split,
        dependency_configs_split,
    ):
        """
        Test that wrong source_guid returns None for historical data.
        """
        # Caller with WRONG source_guid
        caller = caller_records_data[0].copy()
        caller["source_guid"] = "wrong-guid-999"

        agent_config = {"idx": 23, "dependencies": ["split_operation"]}

        file_path = str(
            split_record_temp_dir / "agent_io" / "target" / "node_23_downstream" / "test_file.json"
        )

        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents={},
            agent_name="downstream",
            agent_config=agent_config,
            agent_indices=agent_indices_split,
            dependency_configs=dependency_configs_split,
            current_item=caller,
            file_path=file_path,
        )

        # Should NOT have loaded split_operation (source_guid mismatch)
        assert (
            "split_operation" not in field_context or field_context.get("split_operation") is None
        ), "Should not load data when source_guid doesn't match"
