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
    PermissionError
)

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
    def validate_directory(path: Path, directory_name: str, required: bool = True) -> None:
        """
        Validate that a directory exists and is accessible.
        
        Args:
            path: Path to the directory.
            directory_name: Name of the directory (for error messages).
            required: Whether the directory is required to exist.
            
        Raises:
            DirectoryNotFoundError: If the directory does not exist and is required.
            PermissionError: If the directory is not accessible.
        """
        logger.debug(f"Validating directory: {directory_name} at {path}")
        
        if not path.exists():
            if required:
                error_msg = f"{directory_name} directory does not exist: {path}"
                logger.error(error_msg)
                raise DirectoryNotFoundError(error_msg)
            return
            
        if not path.is_dir():
            error_msg = f"{directory_name} path is not a directory: {path}"
            logger.error(error_msg)
            raise ValidationError(error_msg)
            
        if not os.access(path, os.R_OK):
            error_msg = f"{directory_name} directory is not readable: {path}"
            logger.error(error_msg)
            raise PermissionError(error_msg)
    
    @staticmethod
    def validate_file(path: Path, file_name: str, required: bool = True) -> None:
        """
        Validate that a file exists and is accessible.
        
        Args:
            path: Path to the file.
            file_name: Name of the file (for error messages).
            required: Whether the file is required to exist.
            
        Raises:
            FileNotFoundError: If the file does not exist and is required.
            PermissionError: If the file is not accessible.
        """
        logger.debug(f"Validating file: {file_name} at {path}")
        
        if not path.exists():
            if required:
                error_msg = f"{file_name} file does not exist: {path}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
            return
            
        if not path.is_file():
            error_msg = f"{file_name} path is not a file: {path}"
            logger.error(error_msg)
            raise ValidationError(error_msg)
            
        if not os.access(path, os.R_OK):
            error_msg = f"{file_name} file is not readable: {path}"
            logger.error(error_msg)
            raise PermissionError(error_msg)
    
    @staticmethod
    def create_directory_if_needed(path: Path, directory_name: str) -> None:
        """
        Create a directory if it doesn't exist.
        
        Args:
            path: Path to the directory.
            directory_name: Name of the directory (for error messages).
            
        Raises:
            PermissionError: If the directory cannot be created.
        """
        if not path.exists():
            logger.debug(f"Creating directory: {directory_name} at {path}")
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                error_msg = f"Failed to create {directory_name} directory: {path}: {str(e)}"
                logger.error(error_msg)
                raise PermissionError(error_msg) from e
    
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
            # Current directory
            current_dir = Path.cwd()
            logger.debug(f"Current directory: {current_dir}")
            
            # Prompt directory
            prompt_dir = current_dir / "prompt_store"
            logger.debug(f"Prompt directory: {prompt_dir}")
            
            # Get agent paths from FileHandler
            agent_config_dir, io_dir, _ = cls.get_agent_paths(agent_name)
            logger.debug(f"Agent config directory: {agent_config_dir}")
            logger.debug(f"IO directory: {io_dir}")
            
            # Schema directory
            schema_dir = current_dir / 'schema'
            logger.debug(f"Schema directory: {schema_dir}")
            
            # Default config path
            default_config_path = current_dir / 'agent_actions.yml'
            logger.debug(f"Default config path: {default_config_path}")
            
            # Template directory
            template_dir = current_dir / "templates"
            logger.debug(f"Template directory: {template_dir}")
            
            # Rendered workflows directory
            rendered_workflows_dir = current_dir / "rendered_workflows"
            logger.debug(f"Rendered workflows directory: {rendered_workflows_dir}")
            
            # Create paths container
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
                cls.validate_directory(getattr(paths, dir_name), dir_name)
            
            # Create auto-create directories if they don't exist
            for dir_name in cls.AUTO_CREATE_DIRECTORIES:
                cls.create_directory_if_needed(getattr(paths, dir_name), dir_name)
            
            # Validate default config file
            cls.validate_file(paths.default_config_path, "Default config", required=True)
            
            logger.debug("All project paths created successfully")
            return paths
            
        except Exception as e:
            logger.error(f"Failed to create project paths for agent {agent_name}: {str(e)}")
            
            # Rethrow specific exceptions
            if isinstance(e, (DirectoryNotFoundError, ValidationError, PermissionError, FileNotFoundError)):
                raise
                
            # Otherwise, wrap in a validation error
            raise ValidationError(f"Failed to create project paths for agent {agent_name}: {str(e)}") from e