"""Module for mapping agent names to node directories.

This module has been updated to use simple directory names (action names only)
instead of index-prefixed names (node_X_action_name). The manifest file is now
the single source of truth for execution metadata.
"""

from typing import Dict, Optional


class NodeMappingService:
    """
    Service for mapping agent names to their directory locations.

    Directory naming has been simplified to use action names directly,
    without index prefixes. Use the ManifestManager for execution order
    and dependency information.
    """

    @staticmethod
    def build_agent_index_map(agent_configs: Dict[str, Dict]) -> Dict[str, int]:
        """
        Build a mapping of agent names to their execution indices.

        Note: Indices are still used for execution ordering, but NOT for
        directory naming. Use get_node_directory_name() for directory paths.

        Args:
            agent_configs: Dictionary mapping agent names to their configurations.
                          Each config should have an 'idx' field.

        Returns:
            Dictionary mapping agent names to their indices
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
        Get the execution index for a specific agent.

        Args:
            agent_name: Name of the agent
            agent_indices: Mapping of agent names to indices

        Returns:
            Execution index or None if not found
        """
        return agent_indices.get(agent_name)

    @staticmethod
    def get_node_directory_name(agent_name: str) -> str:
        """
        Get the directory name for an agent.

        Directory names are now simple action names without index prefixes.

        Args:
            agent_name: Name of the agent

        Returns:
            Directory name string (e.g., "fact_extractor")
        """
        return agent_name
