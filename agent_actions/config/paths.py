"""Centralized path management for all agent-actions path operations."""

import logging
import os
import shutil
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from agent_actions.errors.filesystem import FileSystemError

logger = logging.getLogger(__name__)


class PathType(Enum):
    """Enumeration of standard path types in the agent-actions system."""

    PROJECT_ROOT = "project_root"
    AGENT_CONFIG = "agent_config"
    AGENT_IO = "agent_io"
    SOURCE = "source"
    TARGET = "target"
    SCHEMA = "schema"
    PROMPT_STORE = "prompt_store"
    TEMPLATES = "templates"
    RENDERED_WORKFLOWS = "rendered_workflows"
    BATCH = "batch"
    SEED_DATA = "seed_data"


@dataclass
class PathConfig:
    """Configuration for path operations."""

    create_if_missing: bool = True
    validate_permissions: bool = True
    marker_file: str = "agent_actions.yml"
    cache_paths: bool = True


class PathManagerError(FileSystemError):
    """Base exception for PathManager errors."""


class ProjectRootNotFoundError(PathManagerError):
    """Raised when project root cannot be located."""


class PathManagerValidationError(PathManagerError):
    """Raised when path validation fails."""


class PathManager:
    """Centralized path management for agent-actions."""

    # Path templates for standard directory structures
    PATH_TEMPLATES = {
        PathType.AGENT_CONFIG: "{agent_name}/agent_config",
        PathType.AGENT_IO: "{agent_name}/agent_io",
        PathType.SOURCE: "{agent_name}/agent_io/source",
        PathType.TARGET: "{agent_name}/agent_io/target/{action_name}",
        PathType.SCHEMA: "schema",
        PathType.PROMPT_STORE: "prompt_store",
        PathType.TEMPLATES: "templates",
        PathType.RENDERED_WORKFLOWS: "artefact/rendered_workflows",
        PathType.BATCH: "batch",
        PathType.SEED_DATA: "seed_data",
    }

    # Validation rules for different path types
    VALIDATION_RULES = {
        PathType.PROJECT_ROOT: {"must_exist": True, "must_be_readable": True},
        PathType.AGENT_CONFIG: {"must_exist": True, "must_be_readable": True},
        PathType.SOURCE: {"must_be_writable": True},
        PathType.TARGET: {"must_be_writable": True},
        PathType.SCHEMA: {"must_exist": True, "must_be_readable": True},
    }

    def __init__(self, config: PathConfig | None = None, project_root: Path | None = None):
        """Initialize PathManager with optional configuration and project root."""
        self.config = config or PathConfig()
        self._project_root = Path(project_root).resolve() if project_root else None
        # CWD snapshot when _project_root was last resolved from CWD.
        # None means the root was explicitly provided (pinned) and should
        # not be invalidated by CWD changes.
        self._cached_cwd: Path | None = None
        self._path_cache: dict[str, Path] = {}

    def get_project_root(self, start_path: Path | None = None) -> Path:
        """Find and return the project root directory.

        Raises:
            ProjectRootNotFoundError: If project root cannot be found.
        """
        from agent_actions.config.path_config import find_project_root_dir

        # When start_path is None (CWD), return cached root if available
        # and CWD hasn't changed since the root was resolved.
        # When start_path is explicit, always re-resolve (skip reading cache)
        # but still store the result for follow-on calls like get_standard_path().
        read_cache = start_path is None and self.config.cache_paths
        if self._project_root and read_cache:
            # _cached_cwd is None when root was explicitly provided (pinned);
            # otherwise invalidate if the working directory has moved.
            if self._cached_cwd is not None and self._cached_cwd != Path.cwd().resolve():
                self._project_root = None
                self._path_cache.clear()
            else:
                return self._project_root

        search_path = Path(start_path or Path.cwd()).resolve()

        result = find_project_root_dir(search_path, marker_file=self.config.marker_file)
        if result is None:
            raise ProjectRootNotFoundError(
                f"Project root not found. Searched for '{self.config.marker_file}', 'agent_actions', or 'agent_config' "
                f"starting from {search_path}"
            )

        # Warn when found via fallback heuristic (no marker file present)
        if not (result / self.config.marker_file).exists():
            logger.warning(
                "Project root found via fallback heuristic (no marker file '%s'): %s",
                self.config.marker_file,
                result,
            )

        if self.config.cache_paths:
            self._project_root = result
            self._cached_cwd = search_path if start_path is None else None
        return result

    def get_standard_path(
        self,
        path_type: PathType,
        agent_name: str | None = None,
        action_name: str | None = None,
        **template_vars,
    ) -> Path:
        """Get a standard path based on type and parameters."""
        # Resolve project root first — this may clear _path_cache if CWD changed.
        project_root = self.get_project_root()

        cache_key = (
            f"{path_type.value}:{agent_name}:{action_name}:{hash(frozenset(template_vars.items()))}"
        )

        if cache_key in self._path_cache and self.config.cache_paths:
            return self._path_cache[cache_key]

        if path_type == PathType.PROJECT_ROOT:
            path = project_root
        elif path_type in self.PATH_TEMPLATES:
            template = self.PATH_TEMPLATES[path_type]
            format_vars = {"agent_name": agent_name, "action_name": action_name, **template_vars}

            format_vars = {k: v for k, v in format_vars.items() if v is not None}

            try:
                relative_path = template.format(**format_vars)
                path = project_root / relative_path
            except KeyError as e:
                raise PathManagerError(
                    f"Missing required template variable {e} for path type {path_type}"
                ) from e
        else:
            raise PathManagerError(f"Unknown path type: {path_type}")

        resolved_path = path.resolve()

        if self.config.cache_paths:
            self._path_cache[cache_key] = resolved_path

        return resolved_path

    def get_agent_paths(self, agent_name: str) -> dict[str, Path]:
        """Get all standard paths for a specific agent."""
        return {
            "config": self.get_standard_path(PathType.AGENT_CONFIG, agent_name=agent_name),
            "io": self.get_standard_path(PathType.AGENT_IO, agent_name=agent_name),
            "source": self.get_standard_path(PathType.SOURCE, agent_name=agent_name),
        }

    def ensure_path_exists(self, path: Path, is_file: bool = False) -> Path:
        """Ensure a path exists, creating directories as needed."""
        path = Path(path).resolve()

        if is_file:
            directory = path.parent
        else:
            directory = path

        if self.config.create_if_missing:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug("Ensured directory exists: %s", directory)

        return path

    def _check_permissions(
        self, path: Path, requirements: dict[str, bool], errors: list[str]
    ) -> None:
        """Check path permissions and append errors if checks fail."""
        mode = path.stat().st_mode

        permission_checks = [
            ("must_be_readable", os.R_OK, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH, "readable"),
            ("must_be_writable", os.W_OK, stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH, "writable"),
            (
                "must_be_executable",
                os.X_OK,
                stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
                "executable",
            ),
        ]

        for req_key, access_mode, stat_mode, perm_name in permission_checks:
            if requirements.get(req_key, False):
                has_permission = os.access(path, access_mode) and bool(mode & stat_mode)
                if not has_permission:
                    errors.append(f"Path is not {perm_name}: {path}")

    def validate_path(self, path: Path, requirements: dict[str, bool] | None = None) -> bool:
        """Validate a path against requirements.

        Raises:
            PathManagerValidationError: If validation fails and validate_permissions is True.
        """
        path = Path(path).resolve()
        requirements = requirements or {}
        errors = []

        if requirements.get("must_exist", False) and not path.exists():
            errors.append(f"Path does not exist: {path}")

        if path.exists():
            if requirements.get("must_be_file", False) and not path.is_file():
                errors.append(f"Path is not a file: {path}")
            if requirements.get("must_be_directory", False) and not path.is_dir():
                errors.append(f"Path is not a directory: {path}")

            self._check_permissions(path, requirements, errors)

        if errors:
            if self.config.validate_permissions:
                raise PathManagerValidationError("; ".join(errors))
            logger.warning("Path validation warnings: %s", "; ".join(errors))
            return False

        return True

    def validate_standard_path(self, path_type: PathType, path: Path) -> bool:
        """Validate a path against standard requirements for its type."""
        requirements = self.VALIDATION_RULES.get(path_type, {})
        return self.validate_path(path, requirements)

    def normalize_path(self, path: str | Path) -> Path:
        """Normalize a path to a resolved Path object."""
        return Path(path).resolve()

    def is_within_project(self, path: Path) -> bool:
        """Check if a path is within the project root."""
        try:
            project_root = self.get_project_root()
            normalized_path = self.normalize_path(path)
            return project_root in normalized_path.parents or normalized_path == project_root
        except ProjectRootNotFoundError:
            return False

    def get_relative_to_project(self, path: Path) -> Path:
        """Get path relative to project root."""
        project_root = self.get_project_root()
        normalized_path = self.normalize_path(path)
        return normalized_path.relative_to(project_root)

    def find_files_by_pattern(self, pattern: str, base_path: Path | None = None) -> list[Path]:
        """Find files matching a glob pattern within the project."""
        search_base = base_path or self.get_project_root()
        search_base = self.normalize_path(search_base)

        return sorted(search_base.glob(pattern))

    def clean_path(self, path: Path, recursive: bool = False) -> bool:
        """Remove a path, optionally recursively."""
        path = self.normalize_path(path)

        # Note: is_within_project() calls get_project_root() which may resolve
        # from CWD if the manager wasn't primed with an explicit root. Callers
        # should ensure the manager is initialised with project_root or primed
        # via get_project_root(start_path=...) before calling clean_path().
        if not self.is_within_project(path):
            raise ValueError(f"Refusing to delete path outside project root: {path}")

        try:
            if path.exists():
                if path.is_file():
                    path.unlink()
                elif path.is_dir() and recursive:
                    shutil.rmtree(path)
                elif path.is_dir():
                    path.rmdir()  # Only works if empty

                logger.debug("Cleaned path: %s", path)
                return True
        except (OSError, PermissionError) as e:
            logger.error("Failed to clean path %s: %s", path, e)
            return False

        return False

    def create_mirror_path(self, source_path: Path, source_base: str, target_base: str) -> Path:
        """Create a mirrored path by replacing source base with target base."""
        source_path = self.normalize_path(source_path)
        parts = source_path.parts

        try:
            base_index = parts.index(source_base)
        except ValueError as exc:
            raise PathManagerError(
                f"Source base '{source_base}' not found in path {source_path}"
            ) from exc

        new_parts = parts[:base_index] + (target_base,) + parts[base_index + 1 :]

        return Path(*new_parts)

    def clear_cache(self):
        """Clear the internal path cache."""
        self._path_cache.clear()
        self._project_root = None
        self._cached_cwd = None
