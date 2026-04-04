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


_PROJECT_MARKERS = ("agent_actions.yml", "agent_actions.yaml", ".agent_actions.yml")
_FALLBACK_DIRS = ("agent_actions", "agent_config")


def find_project_root_dir(
    start: Path | None = None,
    *,
    marker_file: str | None = None,
    use_fallback_heuristics: bool = True,
) -> Path | None:
    """Walk up from *start* (default CWD) looking for the project root.

    The project root is the directory that contains a marker file
    (``agent_actions.yml`` by default).  When *use_fallback_heuristics* is
    ``True`` (the default) the ``agent_actions/`` and ``agent_config/``
    directories are also accepted as indicators — matching the behaviour of
    :pymethod:`PathManager.get_project_root`.

    Returns the directory containing the marker, or ``None`` if no marker is
    found before the filesystem root.

    This function is intentionally dependency-free (only ``pathlib``) so it
    can be called very early — e.g. to locate ``.env`` before the config
    system boots.
    """
    markers = (marker_file,) if marker_file else _PROJECT_MARKERS
    current = (start or Path.cwd()).resolve()
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            return current
        if use_fallback_heuristics and any((current / d).is_dir() for d in _FALLBACK_DIRS):
            return current
        current = current.parent
    return None


def resolve_project_root(explicit_root: Path | None = None) -> Path:
    """Resolve project root, defaulting to cwd when not provided.

    Args:
        explicit_root: Explicitly provided project root path.

    Returns:
        The explicit root if given, otherwise ``Path.cwd()``.
    """
    return explicit_root or Path.cwd()


def get_project_name(project_root: Path) -> str | None:
    """Return the project name from project configuration, or ``None`` if not set.

    Reads ``project_name`` from ``agent_actions.yml``.  Returns ``None``
    (with a warning) when the key is absent — for backward compatibility
    with projects created before this field was introduced.

    Args:
        project_root: Resolved project root directory.

    Returns:
        Project name string, or ``None`` if not configured.
    """
    try:
        config = load_project_config(project_root)
    except (OSError, ConfigValidationError) as exc:
        logger.debug("Could not load project_name from project config: %s", exc)
        return None

    if not config:
        # No config file found — not an error, just no project config.
        return None

    name = config.get("project_name")
    if not name:
        logger.debug(
            "No 'project_name' in agent_actions.yml — "
            "add 'project_name: <name>' or re-run 'agac init'."
        )
        return None
    return str(name)


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


def get_seed_data_path(project_root: Path) -> str:
    """Return the seed data folder name from project config.

    Reads ``seed_data_path`` from ``agent_actions.yml``.  When no config
    file exists or the key is absent, returns ``"seed_data"`` as the
    conventional default.

    Args:
        project_root: Resolved project root directory.

    Returns:
        Seed data directory name (relative to workflow root).
    """
    try:
        config = load_project_config(project_root)
    except (OSError, ConfigValidationError) as exc:
        logger.debug(
            "Could not load seed_data_path from project config, defaulting to 'seed_data': %s",
            exc,
        )
        return "seed_data"

    raw = config.get("seed_data_path")
    if raw is None:
        return "seed_data"
    name = str(raw)
    # Reject path traversal patterns — seed_data_path must be a simple directory name
    if ".." in name or "/" in name or "\\" in name:
        logger.warning(
            "seed_data_path %r contains path separators or traversal patterns; "
            "using default 'seed_data'",
            name,
        )
        return "seed_data"
    return name
