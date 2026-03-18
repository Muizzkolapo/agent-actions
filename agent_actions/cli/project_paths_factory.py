"""Re-export shim — canonical location is agent_actions.config.project_paths."""

from agent_actions.config.project_paths import (  # noqa: F401
    ProjectPaths,
    ProjectPathsFactory,
    find_config_file,
)
