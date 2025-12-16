"""
Module for initializing new Agent Actions projects.
"""
import logging
from pathlib import Path

import yaml

from agent_actions.utilities.constants import (
    API_KEY_KEY,
    CHUNK_CONFIG_KEY,
    MODEL_NAME_KEY,
)

logger = logging.getLogger(__name__)

class ProjectInitializer:
    """Initialize new Agent Actions projects with standard structure."""

    def __init__(self, project_name: str, base_path: Path=Path.cwd()) -> None:
        """
        Initialize a new ProjectInitializer instance.

        Args:
            project_name (str): Name of the project to create.
            base_path (Path, optional): Base directory path. Defaults to current working directory.
        """
        self.project_name = project_name
        self.project_dir: Path = base_path / project_name
        self.config_dir: Path = self.project_dir / 'agent_config'
        self.schema_dir: Path = self.project_dir / 'schema'
        self.io_dir: Path = self.project_dir / 'agent_io'
        self.config_file: Path = self.project_dir / 'agent_actions.yml'

    def create_directory(self, path: Path) -> None:
        """
        Create a directory if it doesn't exist.

        Args:
            path (Path): Path to the directory to create.
        """
        path.mkdir(parents=True, exist_ok=True)

    def create_file(self, path: Path, content: str='') -> None:
        """
        Create a file if it doesn't exist.

        Args:
            path (Path): Path to the file to create.
            content (str): Content to write to the file.
        """
        if not path.exists():
            path.write_text(content, encoding='utf-8')

    def init_project(self) -> None:
        """
        Initialize the new Agent Actions project by creating directories
        and writing the default configuration file.
        """
        for directory in [self.project_dir, self.config_dir, self.schema_dir, self.io_dir]:
            self.create_directory(directory)
        config_data = {
            'default_agent_config': {
                API_KEY_KEY: 'OPENAI_API_KEY',
                MODEL_NAME_KEY: 'gpt-3.5-turbo',
                CHUNK_CONFIG_KEY: {'chunk_size': 300, 'overlap': 10}
            }
        }
        self.create_file(self.config_file, yaml.dump(config_data))
        logger.info('Successfully initialized project: %s', self.project_name)
