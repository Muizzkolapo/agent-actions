"""
Integration tests for context scope with split records.

These tests verify that the context scope system (observe, drop, passthrough)
works correctly with the deterministic node_id key-join matcher.

Tests the full integration:
    build_field_context_with_history()
        -> _load_historical_node()
            -> HistoricalNodeDataLoader.load_historical_node_data()
                -> _find_target_node_id() + _find_record_by_identifiers()
"""

import json
import tempfile
from pathlib import Path

import pytest

from agent_actions.prompt.context.scope_builder import build_field_context_with_history


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
                └── split_operation/
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
        node_5_dir = target_dir / "split_operation"
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


@pytest.fixture
def context_scope_split():
    """
    Context scope configuration for split record tests.

    Declares which fields from split_operation should be observed.
    """
    return {
        "observe": [
            "split_operation.status",
            "split_operation.tags",
            "split_operation.priority",
        ],
    }


class TestContextScopeSplitRecordsEdgeCases:
    """Edge case tests for context scope with split records."""

    def test_missing_lineage_in_current_item(
        self, split_record_temp_dir, agent_indices_split, dependency_configs_split
    ):
        """
        Test handling when current_item has no lineage.

        Without lineage, _find_target_node_id cannot extract a node_id,
        so the loader returns None. No fallback to source_guid.
        """
        # Current item WITHOUT lineage
        current_item = {
            "source_guid": "test-source-guid-12345",
            "node_id": "node_23_downstream",
            "content": {},
            # NOTE: No lineage field
        }

        agent_config = {
            "idx": 23,
            "dependencies": [],  # Empty - split_operation is a CONTEXT source, not input
            "context_scope": {
                "observe": [
                    "split_operation.status",
                    "split_operation.tags",
                    "split_operation.priority",
                ],
            },
        }

        file_path = str(
            split_record_temp_dir / "agent_io" / "target" / "downstream" / "test_file.json"
        )

        # Should not crash
        field_context = build_field_context_with_history(
            agent_name="downstream",
            agent_config=agent_config,
            agent_indices=agent_indices_split,
            current_item=current_item,
            file_path=file_path,
            context_scope=agent_config["context_scope"],
        )

        assert (
            "split_operation" not in field_context
            or field_context.get("split_operation") is None
            or field_context.get("split_operation") == {}
        ), "Should not load split_operation without lineage or ancestry matching"

    def test_no_storage_backend_returns_none(
        self,
        split_record_temp_dir,
        caller_records_data,
        agent_indices_split,
        dependency_configs_split,
    ):
        """
        Test that without a storage backend, historical data cannot be loaded.

        The deterministic matcher finds the target node_id in lineage, but
        without a storage backend to query, the loader returns None.
        source_guid is not used for matching — only for logging/diagnostics.
        """
        caller = caller_records_data[0].copy()

        agent_config = {
            "idx": 23,
            "dependencies": [],
            "context_scope": {
                "observe": [
                    "split_operation.status",
                    "split_operation.tags",
                    "split_operation.priority",
                ],
            },
        }

        file_path = str(
            split_record_temp_dir / "agent_io" / "target" / "downstream" / "test_file.json"
        )

        # No storage_backend provided — loader will return None
        field_context = build_field_context_with_history(
            agent_name="downstream",
            agent_config=agent_config,
            agent_indices=agent_indices_split,
            current_item=caller,
            file_path=file_path,
            context_scope=agent_config["context_scope"],
        )

        assert (
            "split_operation" not in field_context
            or field_context.get("split_operation") is None
            or field_context.get("split_operation") == {}
        ), "Should not load split_operation without storage backend"
