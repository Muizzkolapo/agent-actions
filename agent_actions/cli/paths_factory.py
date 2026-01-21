"""
Project paths factory service.

This module provides services for creating and validating project directory paths.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from agent_actions.errors import (
    DirectoryError,
    ValidationError,
    FileLoadError,
)  # New modular pattern!
from agent_actions.output.file_handler import FileHandler
from agent_actions.config.paths import PathManager, PathType
from agent_actions.utils.path_utils import resolve_absolute_path
from agent_actions.validation.path_validator import PathValidator

logger = logging.getLogger(__name__)


@dataclass
class ProjectPaths:
    """Container for project directory paths."""

    current_dir: Path
    prompt_dir: Path
    agent_config_dir: Path
    io_dir: Path
    schema_dir: Path
    default_config_path: Path
    template_dir: Path
    rendered_workflows_dir: Path

    def to_dict(self) -> Dict[str, str]:
        """
        Convert paths to a dictionary of strings.

        Returns:
            Dictionary of path names to string paths.
        """
        return {
            "current_dir": str(self.current_dir),
            "prompt_dir": str(self.prompt_dir),
            "agent_config_dir": str(self.agent_config_dir),
            "io_dir": str(self.io_dir),
            "schema_dir": str(self.schema_dir),
            "default_config_path": str(self.default_config_path),
            "template_dir": str(self.template_dir),
            "rendered_workflows_dir": str(self.rendered_workflows_dir),
        }

    def __str__(self) -> str:
        """
        Convert to string representation.

        Returns:
            String representation of the paths.
        """
        paths = self.to_dict()
        return "\n".join([f"{key}: {value}" for key, value in paths.items()])


class ProjectPathsFactory:
    """Factory for creating project paths."""

    REQUIRED_DIRECTORIES = ["agent_config_dir", "schema_dir"]
    AUTO_CREATE_DIRECTORIES = ["prompt_dir", "rendered_workflows_dir", "io_dir"]

    def __init__(self, path_manager: PathManager = None):
        """Initialize factory with optional PathManager."""
        self.path_manager = path_manager or PathManager()

    @staticmethod
    def get_agent_paths(agent_name: str) -> Tuple[Path, Path, Path]:
        """
        Get the agent paths using the FileHandler.

        Args:
            agent_name: Name of the agent.

        Returns:
            Tuple of (agent_config_dir, io_dir, unknown_path).

        Raises:
            ValidationError: If getting agent paths fails.
        """
        try:
            agent_config_dir_str, io_dir_str, unknown_path_str = FileHandler.get_agent_paths(
                agent_name
            )

            # Check if required paths are None and provide helpful error message
            if agent_config_dir_str is None:
                raise ValidationError(
                    f"Agent '{agent_name}' not found. "
                    f"The agent configuration directory '{agent_name}/agent_config' "
                    "does not exist. Please create the agent directory structure "
                    "or check the agent name.",
                    context={
                        "agent_name": agent_name,
                        "operation": "get_agent_paths",
                        "missing_path": "agent_config_dir",
                        "expected_path": f"{agent_name}/agent_config",
                    },
                )

            if io_dir_str is None:
                raise ValidationError(
                    f"Agent IO directory not found for '{agent_name}'. "
                    f"The directory '{agent_name}/agent_io' does not exist. "
                    f"Please create the required directory structure.",
                    context={
                        "agent_name": agent_name,
                        "operation": "get_agent_paths",
                        "missing_path": "io_dir",
                        "expected_path": f"{agent_name}/agent_io",
                    },
                )

            return (Path(agent_config_dir_str), Path(io_dir_str), Path(unknown_path_str or ""))
        except ValidationError:
            # Re-raise ValidationError with its original context
            raise
        except Exception as e:
            logger.error("Failed to get agent paths for %s: %s", agent_name, str(e))
            raise ValidationError(
                "Failed to get agent paths",
                context={"agent_name": agent_name, "operation": "get_agent_paths"},
                cause=e,
            ) from e

    @classmethod
    def create_project_paths(cls, agent_name: str, filename: str) -> ProjectPaths:
        """
        Create project paths for the given agent.

        Args:
            agent_name: Name of the agent.
            filename: Configuration filename.

        Returns:
            ProjectPaths: Container with all project paths.

        Raises:
            Various exceptions if validation fails.
        """
        logger.debug("Creating project paths for agent: %s", agent_name)
        factory = cls()
        try:
            project_root = factory.path_manager.get_project_root()
            prompt_dir = factory.path_manager.get_standard_path(PathType.PROMPT_STORE)
            schema_dir = factory.path_manager.get_standard_path(PathType.SCHEMA)
            template_dir = factory.path_manager.get_standard_path(PathType.TEMPLATES)
            rendered_workflows_dir = factory.path_manager.get_standard_path(
                PathType.RENDERED_WORKFLOWS
            )
            agent_config_dir, io_dir, _ = cls.get_agent_paths(agent_name)
            current_dir = resolve_absolute_path(project_root)
            default_config_path = project_root / "agent_actions.yml"
            paths = ProjectPaths(
                current_dir=current_dir,
                prompt_dir=prompt_dir,
                agent_config_dir=agent_config_dir,
                io_dir=io_dir,
                schema_dir=schema_dir,
                default_config_path=default_config_path,
                template_dir=template_dir,
                rendered_workflows_dir=rendered_workflows_dir,
            )
            path_validator = PathValidator()
            for dir_name in cls.REQUIRED_DIRECTORIES:
                path = getattr(paths, dir_name)
                if dir_name == "schema_dir":
                    factory.path_manager.validate_standard_path(PathType.SCHEMA, path)
                path_validator.validate(path, dir_name)
            for dir_name in cls.AUTO_CREATE_DIRECTORIES:
                path = getattr(paths, dir_name)
                factory.path_manager.ensure_path_exists(path)
                path_validator.validate(path, dir_name)
            path_validator.validate(paths.default_config_path, "Default config")
            logger.debug("All project paths created successfully")
            return paths
        except Exception as e:
            logger.error("Failed to create project paths for agent %s: %s", agent_name, str(e))
            if isinstance(e, (DirectoryError, ValidationError, FileLoadError)):
                raise
            raise ValidationError(
                "Failed to create project paths",
                context={"agent_name": agent_name, "filename": filename},
                cause=e,
            ) from e
