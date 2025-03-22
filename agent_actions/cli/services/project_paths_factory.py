"""
Project paths factory service.
"""

from pathlib import Path
from dataclasses import dataclass
from agent_actions.handlers.file_handler import FileHandler


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


class ProjectPathsFactory:
    """Factory for creating project paths."""
    
    @staticmethod
    def create_project_paths(agent_name: str, filename: str) -> ProjectPaths:
        """
        Create project paths for the given agent.

        Args:
            agent_name: Name of the agent.
            filename: Configuration filename.

        Returns:
            ProjectPaths: Container with all project paths.
        """
        current_dir = Path.cwd()
        prompt_dir = current_dir / "prompt_store"
        agent_config_dir_str, io_dir_str, _ = FileHandler.get_agent_paths(agent_name)
        agent_config_dir = Path(agent_config_dir_str)
        io_dir = Path(io_dir_str)
        schema_dir = current_dir / 'schema'
        default_config_path = current_dir / 'agent_actions.yml'
        template_dir = current_dir / "templates"
        rendered_workflows_dir = current_dir / "rendered_workflows"
        
        return ProjectPaths(
            current_dir=current_dir,
            prompt_dir=prompt_dir,
            agent_config_dir=agent_config_dir,
            io_dir=io_dir,
            schema_dir=schema_dir,
            default_config_path=default_config_path,
            template_dir=template_dir,
            rendered_workflows_dir=rendered_workflows_dir
        )