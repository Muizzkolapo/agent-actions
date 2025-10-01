"""
Project paths factory service.

This module provides services for creating and validating project directory paths.
"""

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Tuple

from agent_actions.agents.handlers.file_handler import FileHandler
from agent_actions.core.exceptions import (
    DirectoryError,
    ValidationError,
    FileLoadError
)
from agent_actions.agents.validators.path_validator import PathValidator
from agent_actions.core.context.path_manager import PathManager, PathType
from agent_actions.core.utils.path_utils import resolve_absolute_path

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
            'current_dir': str(self.current_dir),
            'prompt_dir': str(self.prompt_dir),
            'agent_config_dir': str(self.agent_config_dir),
            'io_dir': str(self.io_dir),
            'schema_dir': str(self.schema_dir),
            'default_config_path': str(self.default_config_path),
            'template_dir': str(self.template_dir),
            'rendered_workflows_dir': str(self.rendered_workflows_dir)
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
    
    # List of required directories to validate
    REQUIRED_DIRECTORIES = ['agent_config_dir', 'schema_dir']
    
    # List of directories that should be created if they don't exist
    AUTO_CREATE_DIRECTORIES = ['prompt_dir', 'rendered_workflows_dir', 'io_dir']
    
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
            agent_config_dir_str, io_dir_str, unknown_path_str = FileHandler.get_agent_paths(agent_name)
            return Path(agent_config_dir_str), Path(io_dir_str), Path(unknown_path_str or "")
        except Exception as e:
            error_msg = f"Failed to get agent paths for {agent_name}: {str(e)}"
            logger.error(error_msg)
            raise ValidationError(
                "Failed to get agent paths",
                context={
                    'agent_name': agent_name,
                    'operation': 'get_agent_paths'
                },
                cause=e
            )
    
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
        logger.debug(f"Creating project paths for agent: {agent_name}")
        
        # Create instance to access PathManager
        factory = cls()
        
        try:
            # Use PathManager for standard paths where possible
            project_root = factory.path_manager.get_project_root()
            
            # Get standard paths using PathManager
            prompt_dir = factory.path_manager.get_standard_path(PathType.PROMPT_STORE)
            schema_dir = factory.path_manager.get_standard_path(PathType.SCHEMA)
            template_dir = factory.path_manager.get_standard_path(PathType.TEMPLATES)
            rendered_workflows_dir = factory.path_manager.get_standard_path(PathType.RENDERED_WORKFLOWS)
            
            # Get agent-specific paths (fallback to FileHandler for compatibility)
            agent_config_dir, io_dir, _ = cls.get_agent_paths(agent_name)
            
            # Use PathManager for project root and config
            current_dir = resolve_absolute_path(project_root)
            default_config_path = project_root / 'agent_actions.yml'
            
            paths = ProjectPaths(
                current_dir=current_dir,
                prompt_dir=prompt_dir,
                agent_config_dir=agent_config_dir,
                io_dir=io_dir,
                schema_dir=schema_dir,
                default_config_path=default_config_path,
                template_dir=template_dir,
                rendered_workflows_dir=rendered_workflows_dir
            )
            
            # Validate required directories using PathManager
            path_validator = PathValidator()
            for dir_name in cls.REQUIRED_DIRECTORIES:
                path = getattr(paths, dir_name)
                # Use PathManager for validation when possible
                if dir_name == 'schema_dir':
                    factory.path_manager.validate_standard_path(PathType.SCHEMA, path)
                path_validator.validate(path, dir_name)
            
            # Create auto-create directories if they don't exist using PathManager
            for dir_name in cls.AUTO_CREATE_DIRECTORIES:
                path = getattr(paths, dir_name)
                # Ensure directories exist using PathManager
                factory.path_manager.ensure_path_exists(path)
                path_validator.validate(path, dir_name)
            
            # Validate default config file
            path_validator.validate(paths.default_config_path, "Default config")
            
            logger.debug("All project paths created successfully")
            return paths
            
        except Exception as e:
            logger.error(f"Failed to create project paths for agent {agent_name}: {str(e)}")
            if isinstance(e, (DirectoryError, ValidationError, FileLoadError)):
                raise
            raise ValidationError(
                "Failed to create project paths",
                context={
                    'agent_name': agent_name,
                    'filename': filename
                },
                cause=e
            )