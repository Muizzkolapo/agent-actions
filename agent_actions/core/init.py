"""
Module for initializing new Agent Actions projects.
"""

import os
import yaml
import logging
from agent_actions.core.exceptions import (
    ProjectInitError,
    DirectoryError,
    FileSystemError
)
from agent_actions.core.error_utils import try_operation, handle_errors

logger = logging.getLogger(__name__)


@handle_errors()
def create_directory(path):
    """
    Create a directory if it doesn't exist.
    
    Args:
        path: Path to the directory to create
        
    Raises:
        DirectoryError: If the directory cannot be created
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path)
    except Exception as e:
        raise DirectoryError(
            directory=path,
            reason=f"Failed to create directory: {e}"
        )


@handle_errors()
def create_file(path, content=""):
    """
    Create a file if it doesn't exist.
    
    Args:
        path: Path to the file to create
        content: Content to write to the file
        
    Raises:
        FileSystemError: If the file cannot be created
    """
    try:
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
    except Exception as e:
        raise FileSystemError(
            error_code="FILE_CREATE_ERROR",
            message=f"Failed to create file: {path}",
            path=path,
            reason=str(e)
        )


@handle_errors()
def init_project(project_name):
    """
    Initialize a new Agent Actions project.
    
    Args:
        project_name: Name of the project to create
        
    Raises:
        ProjectInitError: If the project cannot be initialized
    """
    try:
        # Define project directories
        project_dir = os.path.join(os.getcwd(), project_name)
        config_dir = os.path.join(project_dir, 'agent_config')
        schema_dir = os.path.join(project_dir, 'schema')
        io_dir = os.path.join(project_dir, 'agent_io')
        config_file = os.path.join(project_dir, 'agent_actions.yml')

        # Create directories
        for directory in [project_dir, config_dir, schema_dir, io_dir]:
            create_directory(directory)

        # Create default configuration
        config_data = {
            "default_agent_config": {
                "api_key": "OPENAI_API_KEY",
                "model_name": "gpt-3.5-turbo",
                "chunk_config": {
                    "chunk_size": 300,
                    "overlap": 10
                }
            }
        }
        
        create_file(config_file, yaml.dump(config_data))
        
        logger.info(f"Successfully initialized project: {project_name}")
        
    except (DirectoryError, FileSystemError) as e:
        # Re-raise with more context
        raise ProjectInitError(
            project_name=project_name,
            reason=str(e)
        )
    except Exception as e:
        # Catch any other exceptions
        raise ProjectInitError(
            project_name=project_name,
            reason=f"Unexpected error: {str(e)}"
        )