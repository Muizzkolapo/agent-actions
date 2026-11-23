"""Named database connections a workflow reads its input from and writes its output to."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from agent_actions.connections.base import Connector, Row, WriteMode, json_safe, quoted_identifier
from agent_actions.errors import ConfigurationError

__all__ = [
    "CONNECTORS",
    "Connector",
    "Row",
    "WriteMode",
    "json_safe",
    "open_connection",
    "quoted_identifier",
]

# A connector is imported when a project names its type, so a database driver
# is needed only by the projects that use it.
CONNECTORS: dict[str, str] = {
    "sqlite": "agent_actions.connections.sqlite:SqliteConnector",
}


def open_connection(name: str, project_root: Path) -> Connector:
    """Open the connection the project's ``connections:`` block calls *name*."""
    from agent_actions.config.path_config import load_project_config

    declared = load_project_config(project_root).get("connections") or {}
    settings = declared.get(name) if isinstance(declared, dict) else None
    if not isinstance(settings, dict):
        known = ", ".join(sorted(declared)) if isinstance(declared, dict) and declared else "none"
        raise ConfigurationError(
            f"No connection named '{name}' in agent_actions.yml (declared: {known})",
            context={"connection": name},
        )
    return _connector_class(name, settings).from_settings(settings, project_root)


def _connector_class(name: str, settings: dict[str, Any]) -> type[Connector]:
    kind = settings.get("type")
    target = CONNECTORS.get(str(kind))
    if target is None:
        raise ConfigurationError(
            f"Connection '{name}' has type '{kind}'; the types are {', '.join(sorted(CONNECTORS))}",
            context={"connection": name, "type": kind},
        )
    module_name, _, class_name = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise ConfigurationError(
            f"Connection '{name}' needs a driver that is not installed: {error}. "
            f"Install it with: pip install 'agent-actions[{kind}]'",
            context={"connection": name, "type": kind},
            cause=error,
        ) from error
    connector: type[Connector] = getattr(module, class_name)
    return connector
