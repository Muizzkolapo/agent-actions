"""Tests for HistoricalNodeDataLoader."""
import pytest
import json
from pathlib import Path
from unittest.mock import patch, mock_open
from agent_actions.preprocessing.historical_node_loader import HistoricalNodeDataLoader


class TestHistoricalNodeDataLoader:
    """Test suite for HistoricalNodeDataLoader."""

    def test_find_node_in_lineage_success(self):
        """Test finding a node_id in lineage by action name."""
        lineage = ["node_0_abc123", "node_1_def456", "node_2_ghi789"]
        agent_indices = {"fact_extractor": 0, "flatten_facts": 1, "cluster_list": 2}

        result = HistoricalNodeDataLoader._find_node_in_lineage(
            "fact_extractor", lineage, agent_indices
        )

        assert result == "node_0_abc123"

    def test_find_node_in_lineage_middle_node(self):
        """Test finding a middle node in lineage."""
        lineage = ["node_0_abc123", "node_1_def456", "node_2_ghi789"]
        agent_indices = {"fact_extractor": 0, "flatten_facts": 1, "cluster_list": 2}

        result = HistoricalNodeDataLoader._find_node_in_lineage(
            "flatten_facts", lineage, agent_indices
        )

        assert result == "node_1_def456"

    def test_find_node_in_lineage_not_found(self):
        """Test when node is not in lineage."""
        lineage = ["node_0_abc123", "node_1_def456"]
        agent_indices = {"fact_extractor": 0, "flatten_facts": 1, "cluster_list": 2}

        result = HistoricalNodeDataLoader._find_node_in_lineage(
            "cluster_list", lineage, agent_indices
        )

        assert result is None

    def test_find_node_in_lineage_empty_lineage(self):
        """Test with empty lineage."""
        lineage = []
        agent_indices = {"fact_extractor": 0}

        result = HistoricalNodeDataLoader._find_node_in_lineage(
            "fact_extractor", lineage, agent_indices
        )

        assert result is None

    def test_find_node_in_lineage_missing_agent(self):
        """Test when agent is not in agent_indices."""
        lineage = ["node_0_abc123"]
        agent_indices = {"fact_extractor": 0}

        result = HistoricalNodeDataLoader._find_node_in_lineage(
            "unknown_agent", lineage, agent_indices
        )

        assert result is None

    def test_construct_target_path(self):
        """Test constructing the target file path."""
        current_file_path = "target/node_2_cluster_list/test_file.json"

        result = HistoricalNodeDataLoader._construct_target_path(
            "fact_extractor", 0, current_file_path
        )

        expected = Path("target/node_0_fact_extractor/test_file.json")
        assert result == expected

    def test_construct_target_path_nested(self):
        """Test constructing target path with nested directories."""
        current_file_path = "agent_io/target/node_2_cluster_list/data.json"

        result = HistoricalNodeDataLoader._construct_target_path(
            "flatten_facts", 1, current_file_path
        )

        expected = Path("agent_io/target/node_1_flatten_facts/data.json")
        assert result == expected

    def test_find_record_by_identifiers_success(self):
        """Test finding a record by source_guid and node_id."""
        data = [
            {
                "source_guid": "guid-1",
                "node_id": "node_0_abc123",
                "content": {"fact": "test fact 1"}
            },
            {
                "source_guid": "guid-2",
                "node_id": "node_0_def456",
                "content": {"fact": "test fact 2"}
            },
            {
                "source_guid": "guid-1",
                "node_id": "node_1_ghi789",
                "content": {"fact": "test fact 3"}
            }
        ]

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data, "guid-1", "node_0_abc123"
        )

        assert result is not None
        assert result["content"]["fact"] == "test fact 1"

    def test_find_record_by_identifiers_not_found(self):
        """Test when record is not found."""
        data = [
            {
                "source_guid": "guid-1",
                "node_id": "node_0_abc123",
                "content": {"fact": "test fact 1"}
            }
        ]

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data, "guid-2", "node_0_def456"
        )

        assert result is None

    def test_find_record_by_identifiers_invalid_data(self):
        """Test with invalid data structure."""
        data = "not a list"

        result = HistoricalNodeDataLoader._find_record_by_identifiers(
            data, "guid-1", "node_0_abc123"
        )

        assert result is None

    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.exists")
    def test_load_historical_node_data_success(self, mock_exists, mock_file):
        """Test successful loading of historical node data."""
        # Setup
        lineage = ["node_0_abc123", "node_1_def456"]
        source_guid = "test-guid"
        agent_indices = {"fact_extractor": 0, "flatten_facts": 1}
        file_path = "target/node_1_flatten_facts/test.json"

        mock_exists.return_value = True

        mock_data = [
            {
                "source_guid": "test-guid",
                "node_id": "node_0_abc123",
                "content": {"extracted_fact": "Azure ML feature"}
            }
        ]
        mock_file.return_value.read.return_value = json.dumps(mock_data)

        # Execute
        result = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="fact_extractor",
            lineage=lineage,
            source_guid=source_guid,
            file_path=file_path,
            agent_indices=agent_indices
        )

        # Assert
        assert result is not None
        assert result["extracted_fact"] == "Azure ML feature"

    @patch("pathlib.Path.exists")
    def test_load_historical_node_data_file_not_found(self, mock_exists):
        """Test when target file doesn't exist."""
        mock_exists.return_value = False

        result = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="fact_extractor",
            lineage=["node_0_abc123"],
            source_guid="test-guid",
            file_path="target/node_1_flatten/test.json",
            agent_indices={"fact_extractor": 0}
        )

        assert result is None

    def test_load_historical_node_data_no_lineage(self):
        """Test when lineage is empty."""
        result = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="fact_extractor",
            lineage=[],
            source_guid="test-guid",
            file_path="target/node_1_flatten/test.json",
            agent_indices={"fact_extractor": 0}
        )

        assert result is None

    def test_load_historical_node_data_missing_agent_index(self):
        """Test when agent is not in agent_indices."""
        result = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="unknown_agent",
            lineage=["node_0_abc123"],
            source_guid="test-guid",
            file_path="target/node_1_flatten/test.json",
            agent_indices={"fact_extractor": 0}
        )

        assert result is None

    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.exists")
    def test_load_historical_node_data_record_not_found(self, mock_exists, mock_file):
        """Test when record is not found in file."""
        mock_exists.return_value = True

        mock_data = [
            {
                "source_guid": "different-guid",
                "node_id": "node_0_abc123",
                "content": {"fact": "test"}
            }
        ]
        mock_file.return_value.read.return_value = json.dumps(mock_data)

        result = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="fact_extractor",
            lineage=["node_0_abc123"],
            source_guid="test-guid",
            file_path="target/node_1_flatten/test.json",
            agent_indices={"fact_extractor": 0}
        )

        assert result is None

    @patch("builtins.open", side_effect=Exception("File read error"))
    @patch("pathlib.Path.exists")
    def test_load_historical_node_data_exception_handling(self, mock_exists, mock_file):
        """Test exception handling returns None gracefully."""
        mock_exists.return_value = True

        result = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="fact_extractor",
            lineage=["node_0_abc123"],
            source_guid="test-guid",
            file_path="target/node_1_flatten/test.json",
            agent_indices={"fact_extractor": 0}
        )

        assert result is None
