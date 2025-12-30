"""Tests for NodeMappingService."""

import pytest
from agent_actions.orchestration.node_mapper import NodeMappingService


class TestNodeMappingService:
    """Test suite for NodeMappingService."""

    def test_build_agent_index_map_with_dicts(self):
        """Test building agent index map from dict configs."""
        agent_configs = {
            "fact_extractor": {"idx": 0, "agent_type": "fact_extractor"},
            "flatten_facts": {"idx": 1, "agent_type": "flatten_facts"},
            "cluster_list": {"idx": 2, "agent_type": "cluster_list"},
        }

        result = NodeMappingService.build_agent_index_map(agent_configs)

        assert result == {"fact_extractor": 0, "flatten_facts": 1, "cluster_list": 2}

    def test_build_agent_index_map_empty(self):
        """Test with empty agent_configs."""
        result = NodeMappingService.build_agent_index_map({})

        assert result == {}

    def test_build_agent_index_map_none(self):
        """Test with None agent_configs."""
        result = NodeMappingService.build_agent_index_map(None)

        assert result == {}

    def test_build_agent_index_map_missing_idx(self):
        """Test when some configs don't have idx."""
        agent_configs = {
            "fact_extractor": {"idx": 0, "agent_type": "fact_extractor"},
            "flatten_facts": {"agent_type": "flatten_facts"},  # Missing idx
            "cluster_list": {"idx": 2, "agent_type": "cluster_list"},
        }

        result = NodeMappingService.build_agent_index_map(agent_configs)

        # Should only include agents with idx
        assert result == {"fact_extractor": 0, "cluster_list": 2}

    def test_build_agent_index_map_with_config_objects(self):
        """Test with config objects that have idx attribute."""

        class MockConfig:
            def __init__(self, idx):
                self.idx = idx

        agent_configs = {"fact_extractor": MockConfig(0), "flatten_facts": MockConfig(1)}

        result = NodeMappingService.build_agent_index_map(agent_configs)

        assert result == {"fact_extractor": 0, "flatten_facts": 1}

    def test_build_agent_index_map_mixed_types(self):
        """Test with mixed dict and object configs."""

        class MockConfig:
            def __init__(self, idx):
                self.idx = idx

        agent_configs = {
            "fact_extractor": {"idx": 0},
            "flatten_facts": MockConfig(1),
            "cluster_list": {"idx": 2},
        }

        result = NodeMappingService.build_agent_index_map(agent_configs)

        assert result == {"fact_extractor": 0, "flatten_facts": 1, "cluster_list": 2}

    def test_get_node_index_for_agent_found(self):
        """Test getting node index for an existing agent."""
        agent_indices = {"fact_extractor": 0, "flatten_facts": 1, "cluster_list": 2}

        result = NodeMappingService.get_node_index_for_agent("flatten_facts", agent_indices)

        assert result == 1

    def test_get_node_index_for_agent_not_found(self):
        """Test getting node index for non-existent agent."""
        agent_indices = {"fact_extractor": 0}

        result = NodeMappingService.get_node_index_for_agent("unknown_agent", agent_indices)

        assert result is None

    def test_get_node_index_for_agent_empty_indices(self):
        """Test with empty agent_indices."""
        result = NodeMappingService.get_node_index_for_agent("fact_extractor", {})

        assert result is None

    def test_get_node_prefix(self):
        """Test generating node prefix from index."""
        assert NodeMappingService.get_node_prefix(0) == "node_0"
        assert NodeMappingService.get_node_prefix(1) == "node_1"
        assert NodeMappingService.get_node_prefix(10) == "node_10"

    def test_get_node_directory_name(self):
        """Test generating full node directory name."""
        result = NodeMappingService.get_node_directory_name("fact_extractor", 0)
        assert result == "node_0_fact_extractor"

        result = NodeMappingService.get_node_directory_name("flatten_facts", 1)
        assert result == "node_1_flatten_facts"

        result = NodeMappingService.get_node_directory_name("cluster_list", 2)
        assert result == "node_2_cluster_list"

    def test_build_agent_index_map_with_non_integer_idx(self):
        """Test handling of non-integer idx values."""
        agent_configs = {
            "fact_extractor": {"idx": "0"},  # String instead of int
            "flatten_facts": {"idx": 1},
        }

        result = NodeMappingService.build_agent_index_map(agent_configs)

        # Should include both, even if one is string
        assert result == {"fact_extractor": "0", "flatten_facts": 1}

    def test_build_agent_index_map_idx_zero(self):
        """Test that idx=0 is properly included (not treated as falsy)."""
        agent_configs = {"fact_extractor": {"idx": 0}}

        result = NodeMappingService.build_agent_index_map(agent_configs)

        # idx=0 should be included
        assert result == {"fact_extractor": 0}
