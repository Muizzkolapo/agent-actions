"""Initialize new Agent Actions projects."""

import logging
from pathlib import Path

import yaml

from agent_actions.utils.constants import (
    API_KEY_KEY,
    CHUNK_CONFIG_KEY,
    MODEL_NAME_KEY,
)

logger = logging.getLogger(__name__)


class ProjectInitializer:
    """Initialize new Agent Actions projects with standard structure."""

    def __init__(self, project_name: str, base_path: Path | None = None) -> None:
        """
        Initialize a new ProjectInitializer instance.

        Args:
            project_name (str): Name of the project to create.
            base_path (Path, optional): Base directory path. Defaults to current working directory.
        """
        self.project_name = project_name
        self.project_dir: Path = (base_path or Path.cwd()) / project_name

        # Standard project structure (user-managed directories)
        self.workflow_dir: Path = self.project_dir / "agent_workflow"
        self.prompt_store_dir: Path = self.project_dir / "prompt_store"
        self.schema_dir: Path = self.project_dir / "schema"
        self.templates_dir: Path = self.project_dir / "templates"
        self.tools_dir: Path = self.project_dir / "tools"
        self.config_file: Path = self.project_dir / "agent_actions.yml"

    def create_directory(self, path: Path) -> None:
        """
        Create a directory if it doesn't exist.

        Args:
            path (Path): Path to the directory to create.
        """
        path.mkdir(parents=True, exist_ok=True)

    def create_file(self, path: Path, content: str = "") -> None:
        """
        Create a file if it doesn't exist (atomic check-and-create).

        Args:
            path (Path): Path to the file to create.
            content (str): Content to write to the file.
        """
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(content)
        except FileExistsError:
            logger.debug("File already exists: %s", path)

    def init_project(self) -> None:
        """
        Initialize the new Agent Actions project by creating directories
        and writing the default configuration file.

        Creates the standard project structure:
        - agent_workflow/: Workflow configuration files
        - prompt_store/: Prompt templates
        - schema/: JSON schemas for action outputs
        - templates/: Jinja2 templates for config rendering
        - tools/: Custom tool implementations
        - agent_actions.yml: Project configuration

        Runtime directories (artefact/, logs/, agent_io/) are created automatically during execution.
        """
        # Create standard user-managed directories
        directories = [
            self.project_dir,
            self.workflow_dir,
            self.prompt_store_dir,
            self.schema_dir,
            self.templates_dir,
            self.tools_dir,
        ]

        for directory in directories:
            self.create_directory(directory)

        # Create default configuration file
        config_data = {
            "default_agent_config": {
                API_KEY_KEY: "OPENAI_API_KEY",
                MODEL_NAME_KEY: "gpt-3.5-turbo",
                CHUNK_CONFIG_KEY: {"chunk_size": 300, "overlap": 10},
            }
        }
        self.create_file(self.config_file, yaml.safe_dump(config_data, default_flow_style=False))
        logger.info("Successfully initialized project: %s", self.project_name)
