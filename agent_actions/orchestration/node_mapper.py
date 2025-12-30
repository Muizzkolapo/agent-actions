"""Module for mapping agent names to node indices."""

from typing import Dict, Optional


class NodeMappingService:
    """
    Service for mapping agent names to their node indices in a workflow.

    This service helps resolve historical node references by providing
    the index/position of each agent in the workflow execution order.
    """

    @staticmethod
    def build_agent_index_map(agent_configs: Dict[str, Dict]) -> Dict[str, int]:
        """
        Build a mapping of agent names to their node indices.

        Args:
            agent_configs: Dictionary mapping agent names to their configurations.
                          Each config should have an 'idx' field.

        Returns:
            Dictionary mapping agent names to their indices

        Example:
            agent_configs = {
                "fact_extractor": {"idx": 0, "agent_type": "fact_extractor"},
                "flatten_facts": {"idx": 1, "agent_type": "flatten_facts"},
                "cluster_list": {"idx": 2, "agent_type": "cluster_list"}
            }

            Returns: {
                "fact_extractor": 0,
                "flatten_facts": 1,
                "cluster_list": 2
            }
        """
        if not agent_configs:
            return {}

        agent_index_map = {}

        for agent_name, config in agent_configs.items():
            if isinstance(config, dict):
                idx = config.get("idx")
                if idx is not None:
                    agent_index_map[agent_name] = idx
            elif hasattr(config, "idx"):
                # Support for config objects with idx attribute
                agent_index_map[agent_name] = config.idx

        return agent_index_map

    @staticmethod
    def get_node_index_for_agent(agent_name: str, agent_indices: Dict[str, int]) -> Optional[int]:
        """
        Get the node index for a specific agent.

        Args:
            agent_name: Name of the agent
            agent_indices: Mapping of agent names to indices

        Returns:
            Node index or None if not found
        """
        return agent_indices.get(agent_name)

    @staticmethod
    def get_node_prefix(idx: int) -> str:
        """
        Get the node prefix for a given index.

        Args:
            idx: Node index

        Returns:
            Node prefix string (e.g., "node_0", "node_1")
        """
        return f"node_{idx}"

    @staticmethod
    def get_node_directory_name(agent_name: str, idx: int) -> str:
        """
        Get the full node directory name for an agent.

        Args:
            agent_name: Name of the agent
            idx: Node index

        Returns:
            Directory name string (e.g., "node_0_fact_extractor")
        """
        return f"node_{idx}_{agent_name}"
