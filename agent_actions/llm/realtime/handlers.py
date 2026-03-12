import logging
import os
import shutil
from pathlib import Path

from agent_actions.errors import AgentNotFoundError

logger = logging.getLogger(__name__)


class AgentManager:
    """
    A class for managing agent directories and configurations.
    """

    @staticmethod
    def find_project_root(start_path: Path, marker_file: str = "agent_actions.yml") -> Path | None:
        """
        Find the project root directory by searching for a marker file.

        Args:
            start_path: Path to start searching from
            marker_file: Name of the file that marks the project root (default: 'agent_actions.yml')

        Returns:
            Path to project root if found, None otherwise
        """
        current = Path(start_path).resolve()
        while current != current.parent:
            if (current / marker_file).exists():
                return current
            current = current.parent
        return None

    @staticmethod
    def agent_exists(agent_name: str) -> bool:
        """
        Check if an agent exists.

        Args:
            agent_name: Name of the agent to check.

        Returns:
            True if the agent exists, False otherwise.
        """
        try:
            agent_config_dir, _, _ = AgentManager.get_agent_paths(agent_name)
            return Path(agent_config_dir).exists()
        except AgentNotFoundError:
            return False

    @staticmethod
    def get_agent_paths(agent_name: str) -> tuple[str, str, str]:
        """
        Construct and return key paths related to the agent.
        Searches for agent_actions.yml file to determine the project root,
        then looks for {agent_name}.yml to locate the agent directory.

        Args:
            agent_name: Name of the agent to find paths for

        Returns:
            Tuple of (agent_config_dir, io_dir, logs_dir)

        Raises:
            AgentNotFoundError: If agent_actions.yml or agent configuration cannot be found
        """
        project_root = AgentManager.find_project_root(Path.cwd())
        if not project_root:
            raise AgentNotFoundError(
                "Could not find agent_actions.yml in current or parent directories",
                context={"current_directory": str(Path.cwd()), "marker_file": "agent_actions.yml"},
            )
        agent_yml = f"{agent_name}.yml"
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if "rendered_workflow" not in d]
            if agent_yml in files:
                base_dir = Path(root).parent
                agent_config_dir = base_dir / "agent_config"
                io_dir = base_dir / "agent_io"
                logs_dir = base_dir / "logs"
                return (str(agent_config_dir), str(io_dir), str(logs_dir))
        raise AgentNotFoundError(
            "Could not find configuration for agent",
            context={
                "agent_name": agent_name,
                "project_root": str(project_root),
                "expected_file": f"{agent_name}.yml",
            },
        )

    @classmethod
    def clean_directory(cls, agent: str, directory: Path) -> None:
        """Clean a specific directory for an agent."""
        if directory.exists():
            shutil.rmtree(directory)
            logger.info(f"Cleaned directory {directory} for agent {agent}")
