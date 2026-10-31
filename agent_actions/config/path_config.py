"""Project-specific path configuration loading."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent_actions.errors import ConfigurationError, ConfigValidationError
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
            except yaml.YAMLError as e:
                raise ConfigValidationError(
                    "path_config_yaml",
                    f"Invalid YAML in config file {config_file}",
                    context={"config_path": str(config_file), "operation": "load_config"},
                    cause=e,
                ) from e
            if not isinstance(config, dict):
                raise ConfigValidationError(
                    "path_config_yaml",
                    f"Config file {config_file} must be a mapping at the top level, "
                    f"got {type(config).__name__}",
                    context={"config_path": str(config_file), "operation": "load_config"},
                )
            fire_event(ConfigLoadEvent(config_file=str(config_file), config_type="project"))
            return config

    return {}


# Reported rather than refused: this file has no model, so a raise would be its only
# strict surface. Each value names where the behaviour comes from instead, since a
# reader told only to delete the key loses whatever they meant to set.
_UNREAD_PROJECT_KEYS: dict[str, str] = {
    "output_storage": (
        "the store location is not configurable; each workflow writes "
        "agent_io/store/<workflow>.db inside its own workflow directory"
    ),
}


def warn_unread_project_keys(config: dict[str, Any]) -> None:
    """Report each top-level project-config key that no reader takes."""
    for key in sorted(str(key) for key in config if str(key) in _UNREAD_PROJECT_KEYS):
        logger.warning(
            "project config: '%s' is not read and configures nothing; remove it — %s",
            key,
            _UNREAD_PROJECT_KEYS[key],
        )


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
    (``agent_actions.yml`` by default).  When several markers sit on the walk
    (e.g. a nested ``agent_actions.yml`` dropped by ``agac example install``),
    the **outermost** wins so the parent project stays visible from a nested
    subtree.  When *use_fallback_heuristics* is ``True`` (the default) the
    ``agent_actions/`` and ``agent_config/`` directories are also accepted as
    indicators — matching the behaviour of
    :pymethod:`PathManager.get_project_root`.

    Returns the directory containing the marker, or ``None`` if no marker is
    found before the filesystem root.

    This function is intentionally dependency-free (only ``pathlib``) so it
    can be called very early — e.g. to locate ``.env`` before the config
    system boots.  Callers that need to warn about shadowed nested markers use
    :func:`find_project_root_dir_with_shadow`.
    """
    root, _ = find_project_root_dir_with_shadow(
        start, marker_file=marker_file, use_fallback_heuristics=use_fallback_heuristics
    )
    return root


def find_project_root_dir_with_shadow(
    start: Path | None = None,
    *,
    marker_file: str | None = None,
    use_fallback_heuristics: bool = True,
) -> tuple[Path | None, list[Path]]:
    """Like :func:`find_project_root_dir` but also report shadowed markers.

    Returns ``(root, shadowed)`` where *root* is the outermost marker directory
    (or the fallback-heuristic directory when no marker exists) and *shadowed*
    lists the nested marker directories that were passed over, innermost first.
    A single marker yields an empty *shadowed* list, so the CLI can warn once
    only when a genuine nested-project shadow occurred.  Fallback-heuristic
    directories are never reported as shadowed — they are not marker files.

    Dependency-free (only ``pathlib``) for the same early-boot reason as
    :func:`find_project_root_dir`.
    """
    markers = (marker_file,) if marker_file else _PROJECT_MARKERS
    marker_hits: list[Path] = []
    fallback_hit: Path | None = None
    current = (start or Path.cwd()).resolve()
    while current != current.parent:
        if any((current / m).exists() for m in markers):
            marker_hits.append(current)
        elif (
            fallback_hit is None
            and use_fallback_heuristics
            and any((current / d).is_dir() for d in _FALLBACK_DIRS)
        ):
            fallback_hit = current
        current = current.parent

    if marker_hits:
        return marker_hits[-1], marker_hits[:-1]
    return fallback_hit, []


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


def get_required_by_default(project_root: Path) -> bool:
    """Return the project-wide ``required_by_default`` schema policy.

    Reads the top-level ``required_by_default`` key from ``agent_actions.yml``.
    When set true, flat schema fields with no explicit ``required``/``optional``
    marker are treated as required across every schema, without adding the flag
    to each schema file. Absent config or key defaults to ``False`` (fields
    optional by default). A schema that declares its own ``required_by_default``
    overrides this project setting.
    """
    try:
        config = load_project_config(project_root)
    except (OSError, ConfigValidationError) as exc:
        logger.debug(
            "Could not load required_by_default from project config, defaulting to False: %s",
            exc,
        )
        return False
    return bool(config.get("required_by_default", False))


def get_seed_data_paths(project_root: Path) -> list[Path]:
    """The shared seed folders ``seed_data_paths`` lists, each one inside the project and present.

    A folder that is missing, absolute, or outside the project root once symlinks
    are followed is a configuration error, never skipped.
    """
    try:
        config = load_project_config(project_root)
    except (OSError, ConfigValidationError) as exc:
        logger.debug("Could not load seed_data_paths from project config: %s", exc)
        return []

    raw = config.get("seed_data_paths")
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(entry, str) and entry for entry in raw):
        raise ConfigurationError(
            "seed_data_paths: must be a list of folder names inside the project root.",
            context={"seed_data_paths": raw},
        )

    root = project_root.resolve()
    folders: list[Path] = []
    for entry in raw:
        outside = ConfigurationError(
            f"seed_data_paths: '{entry}' is outside the project. "
            "Use a folder inside the project root.",
            context={"entry": entry, "project_root": str(project_root)},
        )
        if Path(entry).is_absolute():
            raise outside
        resolved = (root / entry).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise outside from None
        if not resolved.is_dir():
            raise ConfigurationError(
                f"seed_data_paths: folder '{entry}' does not exist (project root: {project_root}).",
                context={"entry": entry, "project_root": str(project_root)},
            )
        folders.append(resolved)
    return folders


@dataclass(frozen=True)
class SeedFolder:
    """One folder a seed reference is looked for in; ``kind`` is workflow, project or listed."""

    path: Path
    kind: str
    label: str


@dataclass(frozen=True)
class ResolvedSeedFile:
    """The file a seed reference names, and the shared files a workflow file hides."""

    path: Path
    folder: SeedFolder
    overrides: tuple[Path, ...] = ()


class SeedFileError(ValueError):
    """A seed reference names no file, or a name two shared folders both hold."""


def _workflow_root(workflow_config_path: Path) -> Path:
    current = workflow_config_path.resolve().parent
    search_up = current
    while search_up != search_up.parent:
        if (search_up / "agent_config").exists():
            return search_up
        if search_up.name == "agent_config":
            return search_up.parent
        search_up = search_up.parent
    return current


def _folder_label(path: Path, project_root: Path | None) -> str:
    if project_root is not None:
        try:
            return path.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


def seed_search_folders(
    workflow_config_path: str | None, project_root: Path | None = None
) -> list[SeedFolder]:
    """Every folder a seed reference is looked for in, in search order.

    The workflow's own folder first, then the project folder named by
    ``seed_data_path``, then each folder of ``seed_data_paths`` in order. The
    runtime loader, preflight, the editor and ``inspect`` all search this list,
    so they cannot disagree about which file a name means. A default folder that
    does not exist is left out; a listed one that does not exist is an error.
    """
    from agent_actions.config.paths import PathManager, ProjectRootNotFoundError

    root = project_root
    if root is None:
        start = Path(workflow_config_path).parent if workflow_config_path else None
        try:
            root = PathManager().get_project_root(start_path=start)
        except ProjectRootNotFoundError:
            logger.debug("No project root found from %s", start)

    seed_dir_name = get_seed_data_path(root) if root is not None else "seed_data"
    folders: list[SeedFolder] = []
    seen: set[Path] = set()

    def add(path: Path, kind: str) -> None:
        # One folder is searched once, however many ways it is named: the project
        # folder listed again, a listed folder in two spellings, or the workflow
        # folder of a flat project, which is the project folder and stays its own.
        if path.is_dir() and path not in seen:
            seen.add(path)
            folders.append(SeedFolder(path, kind, _folder_label(path, root)))

    if workflow_config_path:
        add((_workflow_root(Path(workflow_config_path)) / seed_dir_name).resolve(), "workflow")
    if root is not None:
        add((root / seed_dir_name).resolve(), "project")
        for listed in get_seed_data_paths(root):
            add(listed, "listed")

    return folders


def resolve_seed_file(file_spec: str, folders: Sequence[SeedFolder]) -> ResolvedSeedFile:
    """The file *file_spec* names, from the first folder that holds it.

    A workflow folder's file wins over any shared folder's, and the shared files
    it hides are reported as ``overrides``. A name held by more than one shared
    folder is refused, so no run ever picks one of them in silence. A path that
    escapes a folder raises the same ``ValueError`` as before.
    """
    from agent_actions.utils.path_security import FILE_PREFIX, resolve_seed_path

    name = file_spec[len(FILE_PREFIX) :] if file_spec.startswith(FILE_PREFIX) else file_spec
    hits: list[tuple[SeedFolder, Path]] = []
    for folder in folders:
        candidate = resolve_seed_path(file_spec, folder.path)
        if candidate.is_file():
            hits.append((folder, candidate))

    if not hits:
        searched = ", ".join(folder.label for folder in folders) or "no seed folder exists"
        raise SeedFileError(f"Seed file not found: {name}. Searched: {searched}.")

    shared = [(folder, path) for folder, path in hits if folder.kind != "workflow"]
    for folder, path in hits:
        if folder.kind == "workflow":
            return ResolvedSeedFile(path, folder, tuple(path for _, path in shared))
    if len(shared) > 1:
        raise SeedFileError(
            f"Seed file '{name}' is in more than one shared seed folder: "
            f"{', '.join(folder.label for folder, _ in shared)}. Keep it in one."
        )
    folder, path = shared[0]
    return ResolvedSeedFile(path, folder)
