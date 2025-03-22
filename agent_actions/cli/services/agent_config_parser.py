"""
Agent configuration parsing service.
"""

from typing import Dict, Any, List, Optional


class AgentConfigParser:
    """Handles agent configuration parsing operations."""
    
    @staticmethod
    def get_parent_pipeline(agent_config: List[Dict[str, Any]]) -> Optional[str]:
        """
        Get the parent pipeline from the agent configuration.

        Args:
            agent_config: Agent configuration data.

        Returns:
            Parent pipeline name if found, None otherwise.
        """
        for item in agent_config:
            if isinstance(item, dict) and 'parent' in item:
                parent_list = item.get('parent')
                if isinstance(parent_list, list) and parent_list:
                    return parent_list[0]
        return None