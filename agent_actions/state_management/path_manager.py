"""
Centralized path management for agent-actions.

This module provides a unified interface for all path operations,
eliminating hardcoded path structures and duplicated logic.
"""

from pathlib import Path
from typing import Optional, Dict, Union, List
from dataclasses import dataclass
from enum import Enum
import os
import stat
import logging
import shutil

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
    SIDE_OUTPUT = "side_output"
    SEED_DATA = "seed_data"


@dataclass
class PathConfig:
    """Configuration for path operations."""

    create_if_missing: bool = True
    validate_permissions: bool = True
    marker_file: str = "agent_actions.yml"
    cache_paths: bool = True

    @classmethod
    def for_environment(cls, environment: str = "default") -> "PathConfig":
        """Get environment-specific configuration."""
        configs = {
            "test": cls(marker_file="test_agent_actions.yml"),
            "dev": cls(create_if_missing=True),
            "prod": cls(validate_permissions=True, create_if_missing=False),
        }
        return configs.get(environment, cls())


class PathManagerError(Exception):
    """Base exception for PathManager errors."""


class ProjectRootNotFoundError(PathManagerError):
    """Raised when project root cannot be located."""


class PathValidationError(PathManagerError):
    """Raised when path validation fails."""


class PathManager:
    """Centralized path management for agent-actions."""

    # Path templates for standard directory structures
    PATH_TEMPLATES = {
        PathType.AGENT_CONFIG: "{agent_name}/agent_config",
        PathType.AGENT_IO: "{agent_name}/agent_io",
        PathType.SOURCE: "{agent_name}/agent_io/source",
        PathType.TARGET: "{agent_name}/agent_io/target/{node_name}",
        PathType.SCHEMA: "schema",
        PathType.PROMPT_STORE: "prompt_store",
        PathType.TEMPLATES: "templates",
        PathType.RENDERED_WORKFLOWS: "artefact/rendered_workflows",
        PathType.BATCH: "batch",
        PathType.SIDE_OUTPUT: "side_output",
        PathType.SEED_DATA: "seed_data",
    }

    # Validation rules for different path types
    VALIDATION_RULES = {
        PathType.PROJECT_ROOT: {"must_exist": True, "must_be_readable": True},
        PathType.AGENT_CONFIG: {"must_exist": True, "must_be_readable": True},
        PathType.SOURCE: {"create_if_missing": True, "must_be_writable": True},
        PathType.TARGET: {"create_if_missing": True, "must_be_writable": True},
        PathType.SCHEMA: {"must_exist": True, "must_be_readable": True},
    }

    def __init__(self, config: Optional[PathConfig] = None, project_root: Optional[Path] = None):
        """Initialize PathManager with optional configuration and project root."""
        self.config = config or PathConfig()
        self._project_root = Path(project_root).resolve() if project_root else None
        self._path_cache: Dict[str, Path] = {}

    def get_project_root(self, start_path: Optional[Path] = None) -> Path:
        """
        Find and return the project root directory.

        Args:
            start_path: Starting point for search (defaults to current directory)

        Returns:
            Path to project root directory

        Raises:
            ProjectRootNotFoundError: If project root cannot be found
        """
        if self._project_root and self.config.cache_paths:
            return self._project_root

        search_path = Path(start_path or Path.cwd()).resolve()

        # Look for marker file in current and parent directories
        current = search_path
        while current != current.parent:
            marker_path = current / self.config.marker_file
            if marker_path.exists():
                self._project_root = current
                return current

            # Fallback: check for 'agent_actions' (package root) or 'agent_config' directory
            # 'agent_actions' is the definitive project marker per user specification.
            if (current / "agent_actions").is_dir() or (current / "agent_config").is_dir():
                self._project_root = current
                return current

            current = current.parent

        raise ProjectRootNotFoundError(
            f"Project root not found. Searched for '{self.config.marker_file}', 'agent_actions', or 'agent_config' "
            f"starting from {search_path}"
        )

    def get_standard_path(
        self,
        path_type: PathType,
        agent_name: Optional[str] = None,
        node_name: Optional[str] = None,
        **template_vars,
    ) -> Path:
        """
        Get a standard path based on type and parameters.

        Args:
            path_type: Type of path to generate
            agent_name: Agent name for agent-specific paths
            node_name: Node name for target paths
            **template_vars: Additional template variables

        Returns:
            Resolved path for the requested type
        """
        cache_key = (
            f"{path_type.value}:{agent_name}:{node_name}:{hash(frozenset(template_vars.items()))}"
        )

        if cache_key in self._path_cache and self.config.cache_paths:
            return self._path_cache[cache_key]

        project_root = self.get_project_root()

        if path_type == PathType.PROJECT_ROOT:
            path = project_root
        elif path_type in self.PATH_TEMPLATES:
            template = self.PATH_TEMPLATES[path_type]
            format_vars = {"agent_name": agent_name, "node_name": node_name, **template_vars}

            # Filter out None values
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

    def get_agent_paths(self, agent_name: str) -> Dict[str, Path]:
        """
        Get all standard paths for a specific agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Dictionary mapping path names to Path objects
        """
        return {
            "config": self.get_standard_path(PathType.AGENT_CONFIG, agent_name=agent_name),
            "io": self.get_standard_path(PathType.AGENT_IO, agent_name=agent_name),
            "source": self.get_standard_path(PathType.SOURCE, agent_name=agent_name),
        }

    def ensure_path_exists(self, path: Path, is_file: bool = False) -> Path:
        """
        Ensure a path exists, creating directories as needed.

        Args:
            path: Path to ensure exists
            is_file: Whether the path is a file (creates parent directory only)

        Returns:
            The resolved path
        """
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
        self, path: Path, requirements: Dict[str, bool], errors: List[str]
    ) -> None:
        """
        Check path permissions and append errors if checks fail.

        Args:
            path: Path to check
            requirements: Dictionary of permission requirements
            errors: List to append error messages to
        """
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

    def validate_path(self, path: Path, requirements: Optional[Dict[str, bool]] = None) -> bool:
        """
        Validate a path against requirements.

        Args:
            path: Path to validate
            requirements: Dictionary of requirements (must_exist, must_be_readable, etc.)

        Returns:
            True if path meets all requirements

        Raises:
            PathValidationError: If validation fails and validate_permissions is True
        """
        path = Path(path).resolve()
        requirements = requirements or {}
        errors = []

        # Check existence
        if requirements.get("must_exist", False) and not path.exists():
            errors.append(f"Path does not exist: {path}")

        if path.exists():
            # Check if it's the expected type
            if requirements.get("must_be_file", False) and not path.is_file():
                errors.append(f"Path is not a file: {path}")
            if requirements.get("must_be_directory", False) and not path.is_dir():
                errors.append(f"Path is not a directory: {path}")

            # Check permissions using helper method
            self._check_permissions(path, requirements, errors)

        if errors:
            if self.config.validate_permissions:
                raise PathValidationError("; ".join(errors))
            logger.warning("Path validation warnings: %s", "; ".join(errors))
            return False

        return True

    def validate_standard_path(self, path_type: PathType, path: Path) -> bool:
        """
        Validate a path against standard requirements for its type.

        Args:
            path_type: Type of path being validated
            path: Path to validate

        Returns:
            True if path meets standard requirements
        """
        requirements = self.VALIDATION_RULES.get(path_type, {})
        return self.validate_path(path, requirements)

    def normalize_path(self, path: Union[str, Path]) -> Path:
        """
        Normalize a path to a resolved Path object.

        Args:
            path: Path to normalize (string or Path object)

        Returns:
            Normalized and resolved Path object
        """
        return Path(path).resolve()

    def is_within_project(self, path: Path) -> bool:
        """
        Check if a path is within the project root.

        Args:
            path: Path to check

        Returns:
            True if path is within project root
        """
        try:
            project_root = self.get_project_root()
            normalized_path = self.normalize_path(path)
            return project_root in normalized_path.parents or normalized_path == project_root
        except ProjectRootNotFoundError:
            return False

    def get_relative_to_project(self, path: Path) -> Path:
        """
        Get path relative to project root.

        Args:
            path: Absolute path

        Returns:
            Path relative to project root
        """
        project_root = self.get_project_root()
        normalized_path = self.normalize_path(path)
        return normalized_path.relative_to(project_root)

    def find_files_by_pattern(self, pattern: str, base_path: Optional[Path] = None) -> List[Path]:
        """
        Find files matching a pattern within the project or specified base path.

        Args:
            pattern: Glob pattern to match
            base_path: Base path to search (defaults to project root)

        Returns:
            List of matching file paths
        """
        search_base = base_path or self.get_project_root()
        search_base = self.normalize_path(search_base)

        return list(search_base.glob(pattern))

    def clean_path(self, path: Path, recursive: bool = False) -> bool:
        """
        Clean/remove a path.

        Args:
            path: Path to clean
            recursive: Whether to remove directories recursively

        Returns:
            True if successfully cleaned
        """
        path = self.normalize_path(path)

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
        """
        Create a mirrored path by replacing source base with target base.

        This replaces the brittle logic in SourceDataLoader for creating source/target mirrors.

        Args:
            source_path: Original path
            source_base: Base directory name to replace (e.g., "target")
            target_base: Replacement base directory name (e.g., "source")

        Returns:
            Mirrored path
        """
        source_path = self.normalize_path(source_path)
        parts = source_path.parts

        # Find the source base in the path
        try:
            base_index = parts.index(source_base)
        except ValueError as exc:
            raise PathManagerError(
                f"Source base '{source_base}' not found in path {source_path}"
            ) from exc

        # Replace source base with target base
        new_parts = parts[:base_index] + (target_base,) + parts[base_index + 1 :]

        return Path(*new_parts)

    def clear_cache(self):
        """Clear the internal path cache."""
        self._path_cache.clear()
        self._project_root = None
