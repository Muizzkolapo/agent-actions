"""
Project paths factory service.

This module provides services for creating and validating project directory paths.
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

from agent_actions.handlers.file_handler import FileHandler
from agent_actions.cli.exceptions import (
    DirectoryNotFoundError,
    ValidationError,
    FileNotFoundError
)
from agent_actions.cli.validators.path_validator import PathValidator  # Add this import

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
            raise ValidationError(error_msg) from e
    
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
        
        try:
            # Create all paths
            current_dir = Path.cwd()
            prompt_dir = current_dir / "prompt_store"
            agent_config_dir, io_dir, _ = cls.get_agent_paths(agent_name)
            schema_dir = current_dir / 'schema'
            default_config_path = current_dir / 'agent_actions.yml'
            template_dir = current_dir / "templates" 
            rendered_workflows_dir = current_dir / "rendered_workflows"
            
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
            
            # Validate required directories
            for dir_name in cls.REQUIRED_DIRECTORIES:
                PathValidator.validate_directory(getattr(paths, dir_name), dir_name)
            
            # Create auto-create directories if they don't exist
            for dir_name in cls.AUTO_CREATE_DIRECTORIES:
                PathValidator.create_directory_if_needed(getattr(paths, dir_name), dir_name)
            
            # Validate default config file
            PathValidator.validate_file(paths.default_config_path, "Default config")
            
            logger.debug("All project paths created successfully")
            return paths
            
        except Exception as e:
            logger.error(f"Failed to create project paths for agent {agent_name}: {str(e)}")
            if isinstance(e, (DirectoryNotFoundError, ValidationError, FileNotFoundError)):
                raise
            raise ValidationError(f"Failed to create project paths for agent {agent_name}: {str(e)}") from e