"""Project paths factory service."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from agent_actions.errors import (
    DirectoryError,
    ValidationError,
    FileLoadError,
)
from agent_actions.output.file_handler import FileHandler
from agent_actions.config.paths import PathManager, PathType
from agent_actions.utils.path_utils import resolve_absolute_path
from agent_actions.validation.path_validator import PathValidator

logger = logging.getLogger(__name__)


def find_config_file(
    agent_name: str,
    config_dir: Path,
    filename: str,
    *,
    check_alternatives: bool = False,
) -> Path:
    """Find a workflow configuration file.

    Args:
        agent_name: Name of the agent (for error context).
        config_dir: Primary directory to search.
        filename: Configuration filename (e.g., "my_agent.yml").
        check_alternatives: If True, also check parent dir, cwd, and cwd/config.

    Returns:
        Resolved path to the configuration file.

    Raises:
        FileLoadError: If the file is not found.
    """
    full_path = config_dir / filename
    if full_path.exists():
        return full_path

    if check_alternatives:
        parent_dir = config_dir.parent
        alternatives_checked = [
            parent_dir / filename,
            Path.cwd() / filename,
            Path.cwd() / "config" / filename,
        ]
        existing_alternatives = [str(p) for p in alternatives_checked if p.exists()]
        raise FileLoadError(
            "Configuration file not found",
            context={
                "file_path": str(full_path),
                "config_dir": str(config_dir),
                "filename": filename,
                "agent_name": agent_name,
                "alternatives_checked": [str(p) for p in alternatives_checked],
                "found_alternatives": existing_alternatives if existing_alternatives else None,
                "suggestion": (
                    f"File not found at {full_path}. "
                    f"Check if the file exists or use an absolute path."
                    + (
                        f" Found similar file at: {existing_alternatives[0]}"
                        if existing_alternatives
                        else ""
                    )
                ),
            },
        )

    raise FileLoadError(
        "Configuration file not found",
        context={
            "file_path": str(full_path),
            "agent_name": agent_name,
            "suggestion": f"Check if '{filename}' exists in {config_dir}",
        },
    )


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
        paths = self.to_dict()
        return "\n".join([f"{key}: {value}" for key, value in paths.items()])


class ProjectPathsFactory:
    """Factory for creating project paths."""

    REQUIRED_DIRECTORIES = ["agent_config_dir", "schema_dir"]
    AUTO_CREATE_DIRECTORIES = ["prompt_dir", "rendered_workflows_dir", "io_dir", "template_dir"]

    def __init__(self, path_manager: PathManager = None):
        self.path_manager = path_manager or PathManager()

    @staticmethod
    def get_agent_paths(agent_name: str) -> Tuple[Path, Path]:
        try:
            agent_config_dir_str, io_dir_str = FileHandler.get_agent_paths(agent_name)

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

            return (Path(agent_config_dir_str), Path(io_dir_str))
        except ValidationError:
            raise
        except Exception as e:
            logger.error("Failed to get agent paths for %s: %s", agent_name, str(e))
            raise ValidationError(
                "Failed to get agent paths",
                context={"agent_name": agent_name, "operation": "get_agent_paths"},
                cause=e,
            ) from e

    @classmethod
    def create_project_paths(
        cls, agent_name: str, filename: str, *, auto_create: bool = True
    ) -> ProjectPaths:
        """Create project paths. Set auto_create=False for read-only commands."""
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
            agent_config_dir, io_dir = cls.get_agent_paths(agent_name)
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
                if auto_create:
                    factory.path_manager.ensure_path_exists(path)
                if path.exists():
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
