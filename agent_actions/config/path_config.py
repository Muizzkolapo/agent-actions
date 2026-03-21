"""Project-specific path configuration loading."""

from pathlib import Path
from typing import Any

import yaml

from agent_actions.errors import ConfigValidationError
from agent_actions.logging import fire_event
from agent_actions.logging.events import ConfigLoadEvent, ConfigLoadStartEvent


def load_project_config(project_root: Path) -> dict[str, Any]:
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
        project_root / "agent_actions.yml",
        project_root / "agent_actions.yaml",
        project_root / ".agent_actions.yml",
        project_root / "config" / "agent_actions.yml",
    ]

    for config_file in config_files:
        if config_file.exists():
            fire_event(ConfigLoadStartEvent(config_file=str(config_file)))
            try:
                with open(config_file, encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                fire_event(ConfigLoadEvent(config_file=str(config_file), config_type="project"))
                return config
            except yaml.YAMLError as e:
                raise ConfigValidationError(
                    "path_config_yaml",
                    f"Invalid YAML in config file {config_file}",
                    context={"config_path": str(config_file), "operation": "load_config"},
                    cause=e,
                ) from e

    return {}


def get_schema_path(project_root: Path) -> str:
    """Return the schema folder name from project config.

    Reads the ``schema_path`` key from ``agent_actions.yml``.

    Raises:
        ConfigValidationError: If no project config exists or ``schema_path``
            is not defined.  This is a required project-level setting.
    """
    config = load_project_config(project_root)
    if not config:
        raise ConfigValidationError(
            "schema_path_missing",
            f"No agent_actions.yml found in {project_root}. "
            "Project config must define 'schema_path'.",
            context={"project_root": str(project_root), "operation": "get_schema_path"},
        )
    schema_path = config.get("schema_path")
    if not schema_path:
        raise ConfigValidationError(
            "schema_path_missing",
            "Required key 'schema_path' not found in agent_actions.yml. "
            "Add 'schema_path: schema' (or your custom folder name) to your project config.",
            context={"project_root": str(project_root), "operation": "get_schema_path"},
        )
    return schema_path
