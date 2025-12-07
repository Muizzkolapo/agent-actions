"""
Path configuration for agent-actions.

This module provides utilities for loading project-specific configuration files.
"""
from typing import Dict, Any
from pathlib import Path
import yaml
from agent_actions.errors import ConfigValidationError  # New modular pattern!


def load_project_config(project_root: Path) -> Dict[str, Any]:
    """
    Load project-specific configuration from YAML files.

    Searches for configuration files in the following locations (in order):
    - agent_actions.yml
    - agent_actions.yaml
    - .agent_actions.yml
    - config/agent_actions.yml

    Args:
        project_root: Path to project root directory

    Returns:
        Dictionary of project configuration, or empty dict if no config found

    Raises:
        ConfigValidationError: If YAML file exists but contains invalid syntax
    """
    config_files = [
        project_root / 'agent_actions.yml',
        project_root / 'agent_actions.yaml',
        project_root / '.agent_actions.yml',
        project_root / 'config' / 'agent_actions.yml'
    ]

    for config_file in config_files:
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    return yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                raise ConfigValidationError(
                    'path_config_yaml',
                    f'Invalid YAML in config file {config_file}',
                    context={
                        'config_path': str(config_file),
                        'operation': 'load_config'
                    },
                    cause=e
                )

    return {}
