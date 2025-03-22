
"""
Configuration validation utilities.
"""

from pathlib import Path
from typing import Dict, Any, Union, List
from agent_actions.handlers.config_handler import ConfigValidator


class ConfigurationValidator:
    """Handles configuration validation operations."""
    
    @staticmethod
    def validate_agent_config(agent_name: str, config_path: Path, project_dir: Path) -> None:
        """
        Validate the agent configuration file.

        Args:
            agent_name: Name of the agent.
            config_path: Path to the agent configuration file.
            project_dir: Path to the project directory.
            
        Raises:
            ValueError: If configuration validation fails.
        """
        is_unique = ConfigValidator.check_agent_file_unique(str(config_path), str(project_dir))
        if not is_unique:
            raise ValueError(f"Duplicate agent configuration file: {config_path}")

        is_name_unique, error_msg = ConfigValidator.check_agent_name_unique(agent_name, str(project_dir))
        if not is_name_unique:
            raise ValueError(f"Agent name is not unique: {agent_name}. {error_msg}")

    @staticmethod
    def validate_agent_entries(agent_config: Union[List[Dict[str, Any]], Any], agent_name: str) -> None:
        """
        Validate the agent entries in the configuration.

        Args:
            agent_config: Agent configuration data.
            agent_name: Name of the agent.
            
        Raises:
            ValueError: If agent entries validation fails.
        """
        if not isinstance(agent_config, list):
            raise ValueError(f"Agent configuration must be a list for {agent_name}")

        agent_entries = [entry for entry in agent_config if isinstance(entry, dict) and 'agent_type' in entry]
        is_valid, message = ConfigValidator.validate_agent_config(agent_entries)

        if not is_valid:
            raise ValueError(f"Invalid agent configuration for {agent_name}: {message}")
