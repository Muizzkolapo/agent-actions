"""Project-specific path configuration loading."""

import logging
from pathlib import Path
from typing import Any

import yaml

from agent_actions.errors import ConfigValidationError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import ConfigLoadEvent, ConfigLoadStartEvent

logger = logging.getLogger(__name__)


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


def resolve_project_root(explicit_root: Path | None = None) -> Path:
    """Resolve project root, defaulting to cwd when not provided.

    Args:
        explicit_root: Explicitly provided project root path.

    Returns:
        The explicit root if given, otherwise ``Path.cwd()``.
    """
    return explicit_root or Path.cwd()


def get_tool_dirs(project_root: Path) -> list[str]:
    """Resolve tool directory names from project configuration.

    Reads ``tool_path`` from ``agent_actions.yml`` and normalises it to a
    list of directory name strings.  When no config file exists or the key
    is absent, returns ``["tools"]`` as the conventional default.

    Args:
        project_root: Resolved project root directory.

    Returns:
        List of tool directory names (relative to *project_root*).
    """
    try:
        config = load_project_config(project_root)
    except (OSError, ConfigValidationError) as exc:
        logger.debug(
            "Could not load tool_path from project config, defaulting to ['tools']: %s", exc
        )
        return ["tools"]

    raw = config.get("tool_path")
    if raw is None:
        return ["tools"]
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(p) for p in raw]
    return [str(raw)]


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
    return str(schema_path)
